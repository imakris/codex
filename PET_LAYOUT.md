# Pet layout in this fork

This fork keeps transcript history and streaming responses at the full terminal
width when a pet is enabled. Space for the pet is reserved beside the composer,
including its status and hint rows. Short composers grow vertically enough to
contain the sprite; a viewport too small to contain it hides the sprite.

## Origin and adaptation

The starting point is official `openai/codex` main at
`7f6c0f9387`, not the older community branch. The full-width behavior is adapted
from [makoto-soracom's pet branch](https://github.com/makoto-soracom/codex/tree/makoto/pet-flicker-25004),
especially commit `92cda8bea3c81ef6aa699d1e4e611656fe9886f0`
("Fix TUI pet scrollback width and redraw", by makoto-soracom).

The community branch predates the owned transcript layout and the newer
composer rendering options. It cannot be applied unchanged. This adaptation:

- Removes the pet margin from history and all live transcript cells while
  retaining a composer reservation through the current rendering options.
- Reserves enough composer height and protects footer/status text as well as
  the input, so restoring history width does not introduce sprite/text overlap.
- Restricts SIXEL blanking to sprite rows. The previous sprite is cleared before
  reflow, history insertion, or text drawing can put transcript content there.
- Clips saved SIXEL coordinates after terminal resizing and invalidates only
  the erased text-buffer area so those cells are repainted.
- Retains both composer and screen-bottom anchoring, and suppresses the sprite
  for views that do not allocate the composer.

The community branch's image aspect and frame caching changes are not imported.
Its synchronized-output fix (`4cbc56932d0ba144fa5684912097de3c28da27a7`) informs
the redraw transaction: previous sprite cleanup, text/reflow, and replacement
sprite output share one synchronized update. Nested drawing operations do not
end that outer update early. Cursor-position queries remain outside the update,
and failed draws still release it. This avoids showing an erased sprite between
frames while preserving full-width text.

## Installation

Prebuilt Windows x64 and Linux x64 packages are available through GitHub
Releases. See [installation and automatic maintenance](PET_MAINTENANCE.md).

## Verification

The changed TUI tests cover history/stream widths, composer-only reservation,
short and multiline input at normal and narrow widths, sprite clear bounds,
and cleanup after resizing. `ambient_pet_short_composer` records the visible
composer layout. Run the TUI suite with the repository's `just test -p codex-tui`
workflow; compiler-invoking commands must use the configured build queue.

Build and interactive results are reported with the delivered revision rather
than claimed by this document.
