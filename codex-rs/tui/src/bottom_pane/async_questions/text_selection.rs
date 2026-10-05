//! Read-only selection retains raw offsets but copies and highlights only painted source fragments.
//! Gestures capture visible prompt/option blocks so reflow cannot add omitted text to a selection.

use std::ops::Range;
use std::time::Instant;

use crossterm::event::MouseButton;
use crossterm::event::MouseEvent;
use crossterm::event::MouseEventKind;
use ratatui::buffer::Buffer;
use ratatui::layout::Position;
use ratatui::layout::Rect;
use ratatui::style::Modifier;
use unicode_segmentation::UnicodeSegmentation;

use crate::clipboard_copy::CopyStatus;
use crate::text_selection::SelectionUnit;
use crate::tui::TuiEvent;
use crate::width::display_width;

#[derive(Default)]
pub(super) struct QuestionTextSelection {
    question_id: String,
    text: String,
    rows: Vec<SelectionRow>,
    selection: Option<Selection>,
    last_click: Option<(Instant, u16, u16, u8)>,
}

struct SelectionRow {
    area: Rect,
    block: usize,
    source: Range<usize>,
}

#[derive(Debug, PartialEq, Eq)]
struct SelectedFragment {
    block: usize,
    source: Range<usize>,
}

#[derive(Debug, PartialEq, Eq)]
struct SelectionProjection {
    fragments: Vec<SelectedFragment>,
    text: String,
}

struct Selection {
    origin: Range<usize>,
    end: usize,
    unit: SelectionUnit,
    dragging: bool,
    moved: bool,
    fragments: Vec<SelectedFragment>,
    pending_copy: Option<(u64, SelectionProjection)>,
}

impl QuestionTextSelection {
    pub(super) fn begin_layout(&mut self, question_id: &str, text: String) {
        if self.question_id != question_id || self.text != text {
            self.clear();
            self.question_id = question_id.to_string();
            self.text = text;
        }
        self.rows.clear();
    }

    pub(super) fn push_row(&mut self, area: Rect, block: usize, mut source: Range<usize>) {
        let mut used = 0;
        for (offset, grapheme) in self.text[source.clone()].grapheme_indices(true) {
            used += display_width(grapheme);
            if used > usize::from(area.width) {
                source.end = source.start + offset;
                break;
            }
        }
        if !area.is_empty() && !source.is_empty() {
            self.rows.push(SelectionRow {
                area,
                block,
                source,
            });
        }
    }

    pub(super) fn clear(&mut self) -> bool {
        self.last_click = None;
        self.selection.take().is_some()
    }

    pub(super) fn end_drag(&mut self) {
        if let Some(selection) = &mut self.selection {
            selection.dragging = false;
        }
    }

    fn append_fragment(&self, fragments: &mut Vec<SelectedFragment>, fragment: SelectedFragment) {
        if let Some(previous) = fragments.last_mut()
            && previous.block == fragment.block
            && previous.source.end <= fragment.source.start
            && self.text[previous.source.end..fragment.source.start]
                .chars()
                .all(char::is_whitespace)
        {
            previous.source.end = fragment.source.end;
        } else {
            fragments.push(fragment);
        }
    }

    fn gesture_fragments(&self, range: Range<usize>) -> Vec<SelectedFragment> {
        let mut fragments = Vec::new();
        for row in &self.rows {
            let source = range.start.max(row.source.start)..range.end.min(row.source.end);
            if !source.is_empty() {
                self.append_fragment(
                    &mut fragments,
                    SelectedFragment {
                        block: row.block,
                        source,
                    },
                );
            }
        }
        fragments
    }

    fn projection(&self) -> Option<SelectionProjection> {
        let selection = self.selection.as_ref()?;
        let mut fragments = Vec::new();
        for selected in &selection.fragments {
            for row in self.rows.iter().filter(|row| row.block == selected.block) {
                let source = selected.source.start.max(row.source.start)
                    ..selected.source.end.min(row.source.end);
                if !source.is_empty() {
                    self.append_fragment(
                        &mut fragments,
                        SelectedFragment {
                            block: row.block,
                            source,
                        },
                    );
                }
            }
        }
        if fragments.is_empty() {
            return None;
        }
        let mut text = String::new();
        let mut previous_block = None;
        for fragment in &fragments {
            if let Some(previous) = previous_block
                && previous != fragment.block
            {
                text.push_str(if previous == 0 && fragment.block != 0 {
                    "\n\n"
                } else {
                    "\n"
                });
            }
            text.push_str(&self.text[fragment.source.clone()]);
            previous_block = Some(fragment.block);
        }
        Some(SelectionProjection { fragments, text })
    }

    fn contains(&self, event: MouseEvent) -> bool {
        self.rows
            .iter()
            .any(|row| row.area.contains(Position::new(event.column, event.row)))
    }

    fn hit_test(&self, event: MouseEvent) -> Option<usize> {
        let row = self.rows.iter().min_by_key(|row| {
            if event.row < row.area.y {
                row.area.y - event.row
            } else {
                event
                    .row
                    .saturating_sub(row.area.bottom().saturating_sub(1))
            }
        })?;
        let column = usize::from(event.column.saturating_sub(row.area.x).min(row.area.width));
        let mut used = 0;
        for (offset, grapheme) in self.text[row.source.clone()].grapheme_indices(true) {
            let width = display_width(grapheme);
            if column < used + width {
                return Some(row.source.start + offset);
            }
            used += width;
        }
        Some(row.source.end)
    }

    pub(super) fn handle_mouse(&mut self, event: MouseEvent) -> bool {
        let dragging = self
            .selection
            .as_ref()
            .is_some_and(|selection| selection.dragging);
        let down = matches!(event.kind, MouseEventKind::Down(MouseButton::Left));
        match event.kind {
            MouseEventKind::Down(MouseButton::Left)
                if event.modifiers.is_empty() && self.contains(event) => {}
            MouseEventKind::Drag(MouseButton::Left) | MouseEventKind::Up(MouseButton::Left)
                if dragging => {}
            _ => return false,
        }
        if matches!(event.kind, MouseEventKind::Up(MouseButton::Left))
            && self
                .selection
                .as_ref()
                .is_some_and(|selection| !selection.moved)
        {
            self.end_drag();
            return true;
        }
        let Some(offset) = self.hit_test(event) else {
            self.end_drag();
            return false;
        };
        if down {
            let clicks =
                crate::text_selection::click_count(&mut self.last_click, event.column, event.row);
            let unit = SelectionUnit::from_clicks(clicks);
            let origin = unit.range(&self.text, offset);
            self.selection = Some(Selection {
                end: origin.end,
                origin,
                unit,
                dragging: true,
                moved: false,
                fragments: Vec::new(),
                pending_copy: None,
            });
        } else if let Some(selection) = &mut self.selection {
            let range = selection.unit.range(&self.text, offset);
            selection.end = if range.start < selection.origin.start {
                range.start
            } else {
                range.end
            };
            selection.moved = true;
            selection.dragging = !matches!(event.kind, MouseEventKind::Up(MouseButton::Left));
        }
        if let Some(selection) = &self.selection {
            let range =
                selection.origin.start.min(selection.end)..selection.origin.end.max(selection.end);
            let fragments = self.gesture_fragments(range);
            if let Some(selection) = &mut self.selection {
                selection.fragments = fragments;
            }
        }
        true
    }

    pub(super) fn copy_selection(
        &mut self,
        event: &TuiEvent,
        copy: impl FnOnce(&str) -> Result<CopyStatus, String>,
    ) -> Option<(usize, Result<CopyStatus, String>)> {
        let requested = matches!(event, TuiEvent::Key(key) if crate::text_selection::is_copy_key(*key))
            || matches!(event, TuiEvent::Mouse(mouse)
                if mouse.kind == MouseEventKind::Down(MouseButton::Right) && self.contains(*mouse));
        if !requested {
            return None;
        }
        let projection = self.projection()?;
        self.end_drag();
        let count = projection.text.chars().count();
        let result = copy(&projection.text);
        if let Ok(CopyStatus::Pending(id)) = result
            && let Some(selection) = &mut self.selection
        {
            selection.pending_copy = Some((id, projection));
        }
        if result == Ok(CopyStatus::Confirmed) {
            self.clear();
        }
        Some((count, result))
    }

    pub(super) fn has_selection(&self) -> bool {
        self.projection().is_some()
    }

    pub(super) fn finish_copy(
        &mut self,
        completion: &(u64, crate::clipboard_copy::worker::CopyResult),
        current: bool,
    ) -> Option<usize> {
        let pending = self.selection.as_ref()?.pending_copy.as_ref()?;
        if pending.0 != completion.0 {
            return None;
        }
        let (_, projection) = self.selection.as_mut()?.pending_copy.take()?;
        if !current || self.projection().as_ref() != Some(&projection) {
            return None;
        }
        let count = projection.text.chars().count();
        if completion.1 == Ok(CopyStatus::Confirmed) {
            self.clear();
        }
        Some(count)
    }

    pub(super) fn highlight(&self, buf: &mut Buffer) {
        let Some(projection) = self.projection() else {
            return;
        };
        for row in &self.rows {
            let mut x = row.area.x;
            for (offset, grapheme) in self.text[row.source.clone()].grapheme_indices(true) {
                let start = row.source.start + offset;
                let width = u16::try_from(display_width(grapheme)).unwrap_or(u16::MAX);
                let end = x.saturating_add(width).min(row.area.right());
                if projection.fragments.iter().any(|fragment| {
                    fragment.block == row.block
                        && fragment.source.start < start + grapheme.len()
                        && start < fragment.source.end
                }) {
                    for column in x..end {
                        buf[(column, row.area.y)]
                            .modifier
                            .toggle(Modifier::REVERSED);
                    }
                }
                x = end;
            }
        }
    }
}
