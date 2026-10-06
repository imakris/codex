//! Questions route selection to prompt/choice text or the existing inline answer editor.

use super::*;
use crate::clipboard_copy::CopyStatus;
use crate::tui::TuiEvent;
use crossterm::event::MouseButton;
use crossterm::event::MouseEvent;
use crossterm::event::MouseEventKind;
use ratatui::layout::Rect;
use ratatui::text::Line;
use unicode_width::UnicodeWidthStr;

impl AsyncQuestions {
    pub(crate) fn end_mouse_drag(&mut self) {
        self.answer_mouse_ready = false;
        self.text_selection.borrow_mut().end_drag();
        self.composer.end_mouse_drag();
    }

    pub(crate) fn prepare_mouse(&mut self, event: MouseEvent) -> bool {
        self.answer_mouse_ready = self.focus_is_notes() && self.composer.prepare_mouse(event);
        // Read-only question text remains selectable while an answer search owns editor input.
        true
    }

    pub(crate) fn handle_mouse(&mut self, event: MouseEvent) -> bool {
        if self.text_selection.borrow_mut().handle_mouse(event) {
            self.composer.clear_mouse_selection();
            self.snooze_auto_resolution();
            return true;
        }
        if self.answer_mouse_ready && self.focus_is_notes() && self.composer.handle_mouse(event) {
            self.text_selection.borrow_mut().clear();
            self.snooze_auto_resolution();
            return true;
        }
        if matches!(event.kind, MouseEventKind::Down(MouseButton::Left)) {
            self.text_selection.borrow_mut().clear();
        }
        false
    }

    pub(crate) fn copy_selection(
        &mut self,
        event: &TuiEvent,
        copy: impl FnOnce(&str) -> Result<CopyStatus, String>,
    ) -> Option<(usize, Result<CopyStatus, String>)> {
        if self.text_selection.borrow().has_selection() {
            self.text_selection.borrow_mut().copy_selection(event, copy)
        } else if self.focus_is_notes() {
            self.composer.copy_selection(event, copy)
        } else {
            None
        }
    }

    pub(crate) fn finish_copy(
        &mut self,
        completion: &(u64, crate::clipboard_copy::worker::CopyResult),
        current: bool,
    ) -> Option<usize> {
        let editor_current = current && self.focus_is_notes();
        let count = self
            .text_selection
            .borrow_mut()
            .finish_copy(completion, current);
        count.or_else(|| self.composer.finish_copy(completion, editor_current))
    }

    pub(super) fn prepare_text_selection_layout(&self) {
        let Some(answer) = self.current_answer() else {
            return;
        };
        let mut text = answer.question.title.clone();
        if self.has_options() {
            text.push_str("\n\n");
            text.push_str(&self.options().join("\n"));
        }
        self.text_selection
            .borrow_mut()
            .begin_layout(&answer.question_id, text);
    }

    pub(super) fn record_question_rows(&self, area: Rect) {
        let Some(question) = self.current_question() else {
            return;
        };
        for (row, source) in
            crate::wrapping::wrap_ranges_trim(&question.title, usize::from(area.width.max(1)))
                .into_iter()
                .take(usize::from(area.height))
                .enumerate()
        {
            self.text_selection.borrow_mut().push_row(
                Rect::new(area.x, area.y + row as u16, area.width, 1),
                /*block*/ 0,
                source,
            );
        }
    }

    pub(super) fn record_option_rows(&self, area: Rect, first: usize, rows: &[GenericDisplayRow]) {
        if area.is_empty() {
            return;
        }
        let wrapped: Vec<_> = rows
            .iter()
            .skip(first)
            .map(|row| {
                let line = Line::from(row.name.as_str());
                let options = crate::wrapping::RtOptions::new(usize::from(area.width))
                    .subsequent_indent(Line::from(
                        " ".repeat(
                            row.wrap_indent
                                .unwrap_or(0)
                                .min(usize::from(area.width - 1)),
                        ),
                    ));
                crate::wrapping::word_wrap_line_with_source(&line, options)
                    .into_iter()
                    .map(|line| (line.range, line.prefix_bytes))
                    .collect::<Vec<_>>()
            })
            .collect();
        let total_rows = wrapped.iter().map(Vec::len).sum::<usize>();
        let y_offset = area
            .height
            .saturating_sub(u16::try_from(total_rows).unwrap_or(u16::MAX));
        let mut y = area.y + y_offset;
        let mut source_offset = self
            .current_question()
            .map_or(0, |question| question.title.len() + 2)
            + self
                .options()
                .iter()
                .take(first)
                .map(|label| label.len() + 1)
                .sum::<usize>();
        for ((index, row), wrapped) in rows.iter().enumerate().skip(first).zip(wrapped) {
            let prefix = format!(
                "{} {}. ",
                if self.selected_option_index() == Some(index) {
                    '›'
                } else {
                    ' '
                },
                index + 1
            );
            for (range, generated_prefix) in wrapped {
                if y >= area.bottom() {
                    return;
                }
                if index < self.options().len() {
                    let start = range.start.max(prefix.len());
                    let end = range.end.max(prefix.len());
                    let prefix_columns =
                        generated_prefix + row.name[range.start..start.min(range.end)].width();
                    let columns = u16::try_from(prefix_columns)
                        .unwrap_or(u16::MAX)
                        .min(area.width);
                    self.text_selection.borrow_mut().push_row(
                        Rect::new(area.x + columns, y, area.width - columns, 1),
                        /*block*/ index + 1,
                        source_offset + start - prefix.len()..source_offset + end - prefix.len(),
                    );
                }
                y += 1;
            }
            if let Some(label) = self.options().get(index) {
                source_offset += label.len() + 1;
            }
        }
    }
}
