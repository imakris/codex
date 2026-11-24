//! Questions route selection to prompt/choice text or the existing inline answer editor.

use super::*;
use crate::clipboard_copy::CopyStatus;
use crate::terminal_hyperlinks::LogicalLineSource;
use crate::tui::TuiEvent;
use crossterm::event::MouseButton;
use crossterm::event::MouseEvent;
use crossterm::event::MouseEventKind;
use ratatui::layout::Rect;

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

    pub(super) fn prepare_text_selection_layout(
        &self,
        question_lines: &[HyperlinkLine],
        option_lines: &[Vec<HyperlinkLine>],
    ) {
        let question_id = self
            .current_answer()
            .map_or("", |answer| answer.question_id.as_str());
        self.text_selection.borrow_mut().begin_layout(
            question_id,
            std::iter::once(question_lines).chain(option_lines.iter().map(Vec::as_slice)),
        );
    }

    /// Scrolling can clip a choice at either end, so only its painted rows become selectable.
    pub(super) fn record_option_rows(&self, option_lines: &[Vec<HyperlinkLine>]) {
        let viewport = self.option_viewport.borrow();
        let area = viewport.area;
        if area.is_empty() {
            return;
        }
        let (offset, top) = viewport.painted_origin();
        let painted_end = offset + usize::from(area.height);
        let mut selection = self.text_selection.borrow_mut();
        let mut start = 0;
        for (index, lines) in option_lines.iter().enumerate().take(self.options().len()) {
            let end = start + lines.len();
            let first = start.max(offset);
            let last = end.min(painted_end);
            if first < last {
                let rows = Rect::new(
                    area.x,
                    top + (first - offset) as u16,
                    area.width,
                    (last - first) as u16,
                );
                selection.push_block(rows, index + 1, first - start);
            }
            start = end;
        }
    }
}

/// At tiny widths the picker paints a plain label; retain its exact wraps
/// while excluding the numbered gutter from the selectable text.
pub(super) fn exclude_gutter_from_selection(
    lines: &mut [HyperlinkLine],
    label: &str,
    gutter_bytes: usize,
) {
    let origin = LogicalLineSource::new(label.to_string());
    for line in lines {
        let painted = line
            .source
            .take()
            .unwrap_or_else(|| LogicalLineSource::from_line(&line.line));
        let mut source = origin.clone();
        source.prefix_bytes = painted.prefix_bytes
            + painted
                .range
                .end
                .min(gutter_bytes)
                .saturating_sub(painted.range.start);
        source.range = painted.range.start.saturating_sub(gutter_bytes)
            ..painted.range.end.saturating_sub(gutter_bytes);
        line.source = Some(source);
    }
}
