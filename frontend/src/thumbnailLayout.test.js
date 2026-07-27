import test from 'node:test';
import assert from 'node:assert/strict';

import { clampThumbnailPosition } from './thumbnailLayout.js';

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
