//! Questions route selection to prompt/choice text or the existing inline answer editor.

use super::*;
use crate::bottom_pane::selection_popup_common::wrap_row_lines;
use crate::bottom_pane::selection_row_layout::SelectionDescriptionLayout;
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
        rows: &[GenericDisplayRow],
        width: u16,
    ) {
        let options = rows
            .iter()
            .enumerate()
            .map(|(index, row)| {
                let mut lines = wrap_row_lines(
                    row,
                    /*desc_col*/ 0,
                    width,
                    SelectionDescriptionLayout::Columns,
                );
                if row.wrapped_name.is_empty()
                    && let Some(label) = self.options().get(index)
                {
                    // At tiny widths the picker paints a plain label; retain its exact wraps
                    // while excluding the numbered gutter from the selectable text.
                    let prefix = row.name.len() - label.len();
                    let origin = LogicalLineSource::new(label.clone());
                    for line in &mut lines {
                        let painted = line
                            .source
                            .take()
                            .unwrap_or_else(|| LogicalLineSource::from_line(&line.line));
                        let mut source = origin.clone();
                        source.prefix_bytes = painted.prefix_bytes
                            + painted
                                .range
                                .end
                                .min(prefix)
                                .saturating_sub(painted.range.start);
                        source.range = painted.range.start.saturating_sub(prefix)
                            ..painted.range.end.saturating_sub(prefix);
                        line.source = Some(source);
                    }
                }
                lines
            })
            .collect::<Vec<_>>();
        let question_id = self
            .current_answer()
            .map_or("", |answer| answer.question_id.as_str());
        self.text_selection.borrow_mut().begin_layout(
            question_id,
            std::iter::once(question_lines).chain(options.iter().map(Vec::as_slice)),
        );
    }

    pub(super) fn record_option_rows(&self, area: Rect, first: usize, row_count: usize) {
        if area.is_empty() {
            return;
        }
        let mut selection = self.text_selection.borrow_mut();
        let total_rows = (first..row_count)
            .map(|index| selection.block_row_count(index + 1))
            .sum::<usize>();
        let y_offset = area
            .height
            .saturating_sub(u16::try_from(total_rows).unwrap_or(u16::MAX));
        let mut y = area.y + y_offset;
        for index in first..row_count {
            if y >= area.bottom() {
                return;
            }
            let height = u16::try_from(selection.block_row_count(index + 1))
                .unwrap_or(u16::MAX)
                .min(area.bottom() - y);
            if index < self.options().len() {
                selection.push_block(Rect::new(area.x, y, area.width, height), index + 1);
            }
            y += height;
        }
    }
}
