import test from 'node:test';
import assert from 'node:assert/strict';

import {
  clampThumbnailPosition,
  clampThumbnailSize,
} from './thumbnailLayout.js';

test('keeps a secondary stream inside the stream viewport', () => {
  assert.deepEqual(
    clampThumbnailPosition(
      { x: 700, y: 500 },
      { width: 224, height: 126 },
      { width: 800, height: 450 },
    ),
    { x: 576, y: 324 },
  );
});

test('prevents dragging a secondary stream beyond the top or left edge', () => {
  assert.deepEqual(
    clampThumbnailPosition(
      { x: -40, y: -20 },
      { width: 224, height: 126 },
      { width: 800, height: 450 },
    ),
    { x: 0, y: 0 },
  );
});

test('anchors an oversized secondary stream at the viewport origin', () => {
  assert.deepEqual(
    clampThumbnailPosition(
      { x: 40, y: 20 },
      { width: 224, height: 126 },
      { width: 100, height: 80 },
    ),
    { x: 0, y: 0 },
  );
});

test('resizes a secondary stream at 16:9 within the remaining viewport', () => {
  assert.deepEqual(
    clampThumbnailSize(
      500,
      { x: 300, y: 100 },
      { width: 800, height: 400 },
    ),
    { width: 500, height: 281.25 },
  );
});

test('limits resized streams by the closest viewport edge', () => {
  assert.deepEqual(
    clampThumbnailSize(
      500,
      { x: 600, y: 300 },
      { width: 800, height: 450 },
    ),
    { width: 200, height: 112.5 },
  );
});

test('keeps the minimum resize width when there is enough space', () => {
  assert.deepEqual(
    clampThumbnailSize(
      40,
      { x: 0, y: 0 },
      { width: 800, height: 450 },
    ),
    { width: 120, height: 67.5 },
  );
});
