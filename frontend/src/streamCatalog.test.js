import test from 'node:test';
import assert from 'node:assert/strict';

import {
  availableStreams,
  chooseMainStreamPath,
  groupStreamsByDevice,
  secondaryStreams,
  streamUrls,
} from './streamCatalog.js';

const streams = [
  { path: 'birdcam', available: true },
  { path: 'birdcam-pi-01-cam-2', available: true },
  { path: 'birdcam-pi-01-cam-3', available: false },
];

test('builds per-camera WHEP and HLS URLs', () => {
  assert.deepEqual(streamUrls('https://stream.example', 'birdcam-pi-01-cam-2'), {
    whep: 'https://stream.example/birdcam-pi-01-cam-2/whep',
    hls: 'https://stream.example/hls/birdcam-pi-01-cam-2/index.m3u8',
  });
});

test('adds an encoded short-lived access token to both playback URLs', () => {
  assert.deepEqual(
    streamUrls('https://stream.example', 'birdcam', 'signed token+value'),
    {
      whep: 'https://stream.example/birdcam/whep?jwt=signed%20token%2Bvalue',
      hls: 'https://stream.example/hls/birdcam/index.m3u8?jwt=signed%20token%2Bvalue',
    },
  );
});

test('chooses the first transmitted stream and keeps a client-side swap', () => {
  assert.equal(chooseMainStreamPath(streams), 'birdcam');
  assert.equal(
    chooseMainStreamPath(streams, 'birdcam-pi-01-cam-2'),
    'birdcam-pi-01-cam-2',
  );
  assert.equal(chooseMainStreamPath(streams, 'offline'), 'birdcam');
});

test('lists every available stream except the selected primary stream', () => {
  assert.deepEqual(
    secondaryStreams(streams, 'birdcam'),
    [{ path: 'birdcam-pi-01-cam-2', available: true }],
  );
});

test('groups simultaneous streams by transmitter without reordering them', () => {
  const catalog = [
    { pi_id: 'pi-02', path: 'garden', available: true },
    { pi_id: 'pi-01', path: 'feeder', available: true },
    { pi_id: 'pi-01', path: 'nest', available: true },
    { pi_id: 'pi-02', path: 'offline', available: false },
  ];
  assert.deepEqual(groupStreamsByDevice(catalog), [
    {
      pi_id: 'pi-02',
      streams: [{ pi_id: 'pi-02', path: 'garden', available: true }],
    },
    {
      pi_id: 'pi-01',
      streams: [
        { pi_id: 'pi-01', path: 'feeder', available: true },
        { pi_id: 'pi-01', path: 'nest', available: true },
      ],
    },
  ]);
  assert.equal(availableStreams(catalog).length, 3);
});
