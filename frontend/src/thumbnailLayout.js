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

export function clampThumbnailSize(
  desiredWidth,
  position,
  viewportSize,
  {
    minWidth = 120,
    aspectRatio = 16 / 9,
  } = {},
) {
  const safeRatio = aspectRatio > 0 ? aspectRatio : 16 / 9;
  const viewportWidth = Math.max(0, finiteOrZero(viewportSize?.width));
  const viewportHeight = Math.max(0, finiteOrZero(viewportSize?.height));
  const x = Math.max(0, finiteOrZero(position?.x));
  const y = Math.max(0, finiteOrZero(position?.y));
  const maximumWidth = Math.max(
    0,
    Math.min(
      viewportWidth - x,
      (viewportHeight - y) * safeRatio,
    ),
  );
  const effectiveMinimum = Math.min(
    Math.max(0, finiteOrZero(minWidth)),
    maximumWidth,
  );
  const width = Math.min(
    Math.max(effectiveMinimum, finiteOrZero(desiredWidth)),
    maximumWidth,
  );

  return {
    width,
    height: width / safeRatio,
  };
}
