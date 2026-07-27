function finiteOrZero(value) {
  return Number.isFinite(value) ? value : 0;
}

export function clampThumbnailPosition(position, tileSize, viewportSize) {
  const viewportWidth = Math.max(0, finiteOrZero(viewportSize?.width));
  const viewportHeight = Math.max(0, finiteOrZero(viewportSize?.height));
  const tileWidth = Math.max(0, finiteOrZero(tileSize?.width));
  const tileHeight = Math.max(0, finiteOrZero(tileSize?.height));

  return {
    x: Math.min(
      Math.max(0, finiteOrZero(position?.x)),
      Math.max(0, viewportWidth - tileWidth),
    ),
    y: Math.min(
      Math.max(0, finiteOrZero(position?.y)),
      Math.max(0, viewportHeight - tileHeight),
    ),
  };
}
