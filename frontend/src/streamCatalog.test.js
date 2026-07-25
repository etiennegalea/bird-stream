import test from 'node:test';
import assert from 'node:assert/strict';

import { chooseStreamPath, streamUrls } from './streamCatalog.js';

const streams = [
  { path: 'birdcam', available: true },
  { path: 'birdcam-pi-01-cam-2', available: true },
  { path: 'birdcam-pi-01-cam-3', available: false },
];

test('keeps the current camera while it remains available', () => {
  assert.equal(
    chooseStreamPath(streams, 'birdcam-pi-01-cam-2', 'birdcam'),
    'birdcam-pi-01-cam-2',
  );
});

test('restores the saved camera when the current camera disappears', () => {
  assert.equal(
    chooseStreamPath(streams, 'gone', 'birdcam-pi-01-cam-2'),
    'birdcam-pi-01-cam-2',
  );
});

test('never selects disabled or offline cameras', () => {
  assert.equal(
    chooseStreamPath(streams, 'birdcam-pi-01-cam-3', null),
    'birdcam',
  );
  assert.equal(
    chooseStreamPath([{ path: 'offline', available: false }]),
    null,
  );
});

test('builds per-camera WHEP and HLS URLs', () => {
  assert.deepEqual(streamUrls('https://stream.example', 'birdcam-pi-01-cam-2'), {
    whep: 'https://stream.example/birdcam-pi-01-cam-2/whep',
    hls: 'https://stream.example/hls/birdcam-pi-01-cam-2/index.m3u8',
  });
});
