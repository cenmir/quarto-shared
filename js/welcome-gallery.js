// Sticky zoom for the .welcomeContent gallery on a book's landing page.
// The enlarged state is CSS (.zoomed in custom.scss); this only toggles the
// class, so that a tap gives touch devices the preview that :hover gives a
// pointer. At most one tile is zoomed at a time, and a click anywhere else
// clears it.

document.addEventListener('DOMContentLoaded', function() {
  const tiles = document.querySelectorAll('.welcomeContent > img, .welcomeContent > video');
  if (!tiles.length) {
    return;
  }

  function clearZoom() {
    document.querySelectorAll('.welcomeContent .zoomed').forEach(tile => {
      tile.classList.remove('zoomed');
    });
  }

  tiles.forEach(tile => {
    tile.addEventListener('click', event => {
      const wasZoomed = tile.classList.contains('zoomed');
      clearZoom();
      if (!wasZoomed) {
        tile.classList.add('zoomed');
      }
      // Without this the document handler below would immediately undo it
      event.stopPropagation();
    });
  });

  document.addEventListener('click', clearZoom);

  // Escape is the conventional way out of an enlarged image
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      clearZoom();
    }
  });
});
