//! Question orchestration retains input buffers and renders pending-question summaries.
use super::*;
use crossterm::event::KeyModifiers;
use pretty_assertions::assert_eq;
use tokio::sync::mpsc::unbounded_channel;

fn selectable_question_pane(title: &str, options: Option<Vec<String>>) -> BottomPane {
    let (tx, _rx) = unbounded_channel();
    let mut pane = super::tests::test_pane(AppEventSender::new(tx));
    pane.push_async_questions(
        "message",
        &[codex_protocol::items::AsyncUserInputQuestion {
            title: title.into(),
            options,
        }],
    );
    pane.questions.as_mut().unwrap().set_expanded(true);
    pane
}

fn render_question(pane: &BottomPane, area: Rect) -> Buffer {
    let mut buffer = Buffer::empty(area);
    pane.render(area, &mut buffer);
    buffer
}

fn question_text_start(buffer: &Buffer, text: &str) -> (u16, u16) {
    let area = buffer.area;
    for y in area.y..area.bottom() {
        for x in area.x..area.right() {
            let suffix = (x..area.right())
                .map(|column| buffer[(column, y)].symbol())
                .collect::<String>();
            if suffix.starts_with(text) {
                return (x, y);
            }
        }
    }
    panic!("question text {text:?} not visible");
}

fn select_question_text(
    pane: &mut BottomPane,
    buffer: &Buffer,
    start: (u16, u16),
    end: (u16, u16),
) {
    use crossterm::event::MouseButton::Left;
    use crossterm::event::MouseEventKind::{Down, Drag, Up};
    for (kind, (column, row)) in [(Down(Left), start), (Drag(Left), end), (Up(Left), end)] {
        let event = crossterm::event::MouseEvent {
            kind,
            column,
            row,
            modifiers: KeyModifiers::NONE,
        };
        assert!(pane.prepare_composer_mouse(event));
        let rendered = render_question(pane, buffer.area);
        assert!(
            pane.handle_composer_mouse(event),
            "unhandled {event:?} in {rendered:?}"
        );
    }
}

fn copy_question_text(
    pane: &mut BottomPane,
    status: crate::clipboard_copy::CopyStatus,
) -> Option<String> {
    let mut copied = None;
    pane.copy_composer_selection(
        &crate::tui::TuiEvent::Key(KeyEvent::new(KeyCode::Insert, KeyModifiers::CONTROL)),
        |text| {
            copied = Some(text.to_string());
            Ok(status)
        },
    );
    copied
}

#[test]
fn expanded_question_selection_preserves_unicode_source_after_resize() {
    let title = "Route 👨‍👩‍👧‍👦  café 界\n👩🏽‍💻 along the river?";
    let mut pane = selectable_question_pane(title, None);
    let buffer = render_question(&pane, Rect::new(7, 4, 28, 18));
    let start = question_text_start(&buffer, "Route");
    let last = question_text_start(&buffer, "?");
    select_question_text(&mut pane, &buffer, (last.0 + 1, last.1), start);
    render_question(&pane, Rect::new(2, 1, 45, 18));
    assert_eq!(
        copy_question_text(&mut pane, crate::clipboard_copy::CopyStatus::Confirmed).as_deref(),
        Some(title)
    );
    assert!(pane.questions.as_ref().unwrap().submission.is_none());
}

#[test]
fn expanded_question_option_copy_omits_markers_and_soft_wraps() {
    let label = "Scenic 👨‍👩‍👧‍👦 route through café gardens!";
    let mut pane = selectable_question_pane("Choose a route?", Some(vec![label.into()]));
    let buffer = render_question(&pane, Rect::new(3, 2, 29, 18));
    let start = question_text_start(&buffer, "Scenic");
    let last = question_text_start(&buffer, "!");
    select_question_text(&mut pane, &buffer, start, (last.0 + 1, last.1));
    assert_eq!(
        copy_question_text(&mut pane, crate::clipboard_copy::CopyStatus::Confirmed).as_deref(),
        Some(label)
    );
    pane.handle_key_event(KeyCode::Enter.into());
    assert!(matches!(
        pane.questions.as_ref().unwrap().submission,
        Some(QuestionSubmission::Submit(_))
    ));
}

#[test]
fn expanded_question_copy_completion_tracks_selection_owner() {
    use crate::clipboard_copy::CopyStatus;
    let mut pane = selectable_question_pane("Question text?", None);
    let buffer = render_question(&pane, Rect::new(0, 0, 50, 12));
    let start = question_text_start(&buffer, "Question");
    select_question_text(&mut pane, &buffer, start, (start.0 + 8, start.1));
    assert_eq!(
        copy_question_text(&mut pane, CopyStatus::Pending(11)).as_deref(),
        Some("Question")
    );
    assert_eq!(
        pane.finish_composer_copy(&(11, Ok(CopyStatus::Unconfirmed)), true),
        Some(8)
    );
    assert_eq!(
        copy_question_text(&mut pane, CopyStatus::Pending(12)).as_deref(),
        Some("Question")
    );
    assert_eq!(
        pane.finish_composer_copy(&(12, Ok(CopyStatus::Confirmed)), true),
        Some(8)
    );
    assert_eq!(copy_question_text(&mut pane, CopyStatus::Confirmed), None);

    select_question_text(&mut pane, &buffer, start, (start.0 + 8, start.1));
    copy_question_text(&mut pane, CopyStatus::Pending(13));
    pane.questions.as_mut().unwrap().set_expanded(false);
    assert_eq!(
        pane.finish_composer_copy(&(13, Ok(CopyStatus::Confirmed)), true),
        None
    );
    pane.questions.as_mut().unwrap().set_expanded(true);
    render_question(&pane, Rect::new(0, 0, 50, 12));
    assert_eq!(copy_question_text(&mut pane, CopyStatus::Confirmed), None);
}

#[test]
fn expanded_question_answer_editor_owns_its_draft_selection() {
    use crate::clipboard_copy::CopyStatus;
    for options in [None, Some(vec!["Named answer".into()])] {
        let mut pane = selectable_question_pane("Question?", options.clone());
        pane.set_composer_text("Main draft".into(), Vec::new(), Vec::new());
        if options.is_some() {
            pane.handle_key_event(KeyCode::Char('2').into());
        }
        pane.handle_paste("Typed answer".into());
        let buffer = render_question(&pane, Rect::new(0, 0, 50, 18));
        let start = question_text_start(&buffer, "Typed");
        select_question_text(&mut pane, &buffer, start, (start.0 + 5, start.1));
        assert_eq!(
            copy_question_text(&mut pane, CopyStatus::Confirmed).as_deref(),
            Some("Typed")
        );
        assert_eq!(
            pane.questions.as_ref().unwrap().composer.current_text(),
            "Typed answer"
        );
        assert_eq!(pane.composer_text(), "Main draft");
        assert!(pane.questions.as_ref().unwrap().submission.is_none());
    }
}

#[test]
fn expanded_question_search_keeps_answer_mouse_ownership() {
    use crossterm::event::MouseButton::Left;
    use crossterm::event::MouseEventKind::Down;
    use crossterm::event::MouseEventKind::Up;

    for options in [None, Some(vec!["Named answer".into()])] {
        for vim in [false, true] {
            let mut pane = selectable_question_pane("Question?", options.clone());
            if options.is_some() {
                pane.handle_key_event(KeyCode::Char('2').into());
            }
            pane.handle_paste("Typed answer".into());
            let composer = &mut pane.questions.as_mut().unwrap().composer;
            if vim {
                composer.set_vim_enabled(true);
                composer.handle_key_event(KeyCode::Esc.into());
                composer.handle_key_event(KeyCode::Char('/').into());
            } else {
                composer.handle_key_event(KeyEvent::new(KeyCode::Char('r'), KeyModifiers::CONTROL));
            }
            let before = composer.snapshot_draft();
            let area = Rect::new(0, 0, 50, 18);
            let buffer = render_question(&pane, area);
            let (column, row) = question_text_start(&buffer, "Typed");
            for kind in [Down(Left), Up(Left), Down(Left), Up(Left)] {
                let event = crossterm::event::MouseEvent {
                    kind,
                    column,
                    row,
                    modifiers: KeyModifiers::NONE,
                };
                assert!(
                    !pane
                        .questions
                        .as_mut()
                        .unwrap()
                        .composer
                        .prepare_mouse(event)
                );
                pane.prepare_composer_mouse(event);
                render_question(&pane, area);
                assert!(!pane.handle_composer_mouse(event));
            }
            assert_eq!(
                pane.questions.as_ref().unwrap().composer.snapshot_draft(),
                before
            );
            assert_eq!(
                copy_question_text(&mut pane, crate::clipboard_copy::CopyStatus::Confirmed),
                None
            );

            let start = question_text_start(&buffer, "Question");
            select_question_text(&mut pane, &buffer, start, (start.0 + 8, start.1));
            assert_eq!(
                copy_question_text(&mut pane, crate::clipboard_copy::CopyStatus::Confirmed)
                    .as_deref(),
                Some("Question")
            );
            assert_eq!(
                pane.questions.as_ref().unwrap().composer.snapshot_draft(),
                before
            );
        }
    }
}

#[test]
fn expanded_question_click_units_and_copy_failure_keep_source_selection() {
    use crate::clipboard_copy::CopyStatus;
    use crossterm::event::MouseButton::Left;
    use crossterm::event::MouseEventKind::{Down, Up};
    let mut pane = selectable_question_pane("Question text?", None);
    let buffer = render_question(&pane, Rect::new(0, 0, 50, 12));
    let (column, row) = question_text_start(&buffer, "Question");
    for clicks in 1..=3 {
        for kind in [Down(Left), Up(Left)] {
            let event = crossterm::event::MouseEvent {
                kind,
                column,
                row,
                modifiers: KeyModifiers::NONE,
            };
            assert!(pane.prepare_composer_mouse(event));
            let rendered = render_question(&pane, buffer.area);
            assert!(
                pane.handle_composer_mouse(event),
                "click {clicks}, unhandled {event:?} in {rendered:?}"
            );
        }
        if clicks == 1 {
            continue;
        }
        let expected = if clicks == 2 {
            "Question"
        } else {
            "Question text?"
        };
        assert_eq!(
            copy_question_text(&mut pane, CopyStatus::Unconfirmed).as_deref(),
            Some(expected)
        );
        let result = pane.copy_composer_selection(
            &crate::tui::TuiEvent::Key(KeyEvent::new(KeyCode::Insert, KeyModifiers::CONTROL)),
            |text| {
                assert_eq!(text, expected);
                Err("clipboard unavailable".into())
            },
        );
        assert_eq!(
            result,
            Some((
                expected.chars().count(),
                Err("clipboard unavailable".into())
            ))
        );
    }
    pane.handle_key_event(KeyCode::Esc.into());
    assert!(pane.questions.as_ref().unwrap().expanded);
    assert_eq!(copy_question_text(&mut pane, CopyStatus::Confirmed), None);
}

#[test]
fn expanded_question_clipped_selection_does_not_authorize_hidden_options() {
    let mut pane = selectable_question_pane(
        "Question?",
        Some(vec![
            "Scenic route through the mountains past the distant hidden destination!".into(),
        ]),
    );
    let buffer = render_question(&pane, Rect::new(0, 0, 22, 8));
    let start = question_text_start(&buffer, "Scenic");
    select_question_text(&mut pane, &buffer, start, (22, 8));
    let copied =
        copy_question_text(&mut pane, crate::clipboard_copy::CopyStatus::Confirmed).unwrap();
    assert!(copied.starts_with("Scenic"));
    assert!(!copied.contains("hidden destination"));
    pane.handle_key_event(KeyCode::Enter.into());
    assert!(pane.questions.as_ref().unwrap().submission.is_none());
}

#[test]
fn expanded_question_prompt_supports_mouse_selection_and_copy() {
    use crate::clipboard_copy::CopyStatus;
    use crate::tui::TuiEvent;
    use crossterm::event::MouseButton;
    use crossterm::event::MouseEvent;
    use crossterm::event::MouseEventKind;
    use ratatui::buffer::Buffer;

    let (tx, _rx) = unbounded_channel();
    let mut pane = super::tests::test_pane(AppEventSender::new(tx));
    pane.push_async_questions(
        "message",
        &[codex_protocol::items::AsyncUserInputQuestion {
            title: "Which route?".into(),
            options: Some(vec!["Scenic route".into(), "Direct route".into()]),
        }],
    );
    pane.questions.as_mut().unwrap().set_expanded(true);
    let area = Rect::new(0, 0, 60, 18);
    let mut buffer = Buffer::empty(area);
    pane.as_renderable().render(area, &mut buffer);
    let row = (0..area.height)
        .find(|&y| {
            (0..area.width)
                .map(|x| buffer[(x, y)].symbol())
                .collect::<String>()
                .contains("Which route?")
        })
        .expect("visible question prompt");
    let column = (0..area.width)
        .find(|&x| buffer[(x, row)].symbol() == "W")
        .unwrap();
    for kind in [
        MouseEventKind::Down(MouseButton::Left),
        MouseEventKind::Drag(MouseButton::Left),
        MouseEventKind::Up(MouseButton::Left),
    ] {
        let event = MouseEvent {
            kind,
            column: column + u16::from(!matches!(kind, MouseEventKind::Down(_))) * 5,
            row,
            modifiers: KeyModifiers::NONE,
        };
        assert!(pane.prepare_composer_mouse(event));
        assert!(pane.handle_composer_mouse(event));
    }
    let mut copied = None;
    let result = pane.copy_composer_selection(
        &TuiEvent::Key(KeyEvent::new(KeyCode::Insert, KeyModifiers::CONTROL)),
        |text| {
            copied = Some(text.to_string());
            Ok(CopyStatus::Confirmed)
        },
    );
    assert_eq!(copied.as_deref(), Some("Which"));
    assert_eq!(result, Some((5, Ok(CopyStatus::Confirmed))));
    assert!(pane.questions.as_ref().unwrap().submission.is_none());
}

#[test]
fn questions_flush_buffered_typing_and_record_activity() {
    let (tx, _rx) = unbounded_channel();
    let mut pane = super::tests::test_pane(AppEventSender::new(tx));
    let questions = [codex_protocol::items::AsyncUserInputQuestion {
        title: "Which way?".into(),
        options: None,
    }];
    pane.push_async_questions("message", &questions);
    pane.questions
        .as_mut()
        .unwrap()
        .set_expanded(/*expanded*/ true);
    pane.handle_paste("pasted ".into());
    assert!(pane.last_composer_activity_at.is_some());
    pane.last_composer_activity_at = None;
    for ch in "answer".chars() {
        pane.handle_key_event(KeyEvent::from(KeyCode::Char(ch)));
    }
    assert!(pane.last_composer_activity_at.is_some());
    std::thread::sleep(paste_burst::PasteBurst::recommended_active_flush_delay());
    assert!(pane.flush_paste_burst_if_due());
    assert_eq!(
        pane.questions.as_ref().unwrap().composer.current_text(),
        "pasted answer"
    );
    pane.questions
        .as_mut()
        .unwrap()
        .set_expanded(/*expanded*/ false);
    pane.push_async_questions("next", &questions);
    let now = Instant::now() + Duration::from_secs(15);
    insta::assert_snapshot!(
        "question_collapsed_countdown",
        pane.question_summary(now)
            .unwrap()
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join("\n")
    );
    let editor = pane.questions.as_mut().unwrap();
    assert!(editor.countdown(now + Duration::from_secs(30)).is_none());
    editor.set_expanded(/*expanded*/ true);
    editor.append("while-open", &questions);
    assert!(editor.countdown(now).is_none());
}
