import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEVICE_TEMP_HOT_C,
  DEVICE_TEMP_WARNING_C,
  temperatureState,
} from './deviceStatus.js';

test('classifies normal, hot, and warning transmitter temperatures', () => {
  assert.equal(temperatureState(42).level, 'normal');
  assert.equal(temperatureState(DEVICE_TEMP_HOT_C).level, 'hot');
  assert.equal(temperatureState(79.9).level, 'hot');
  assert.equal(temperatureState(DEVICE_TEMP_WARNING_C).level, 'warning');
});

test('ignores missing or invalid temperatures', () => {
  assert.equal(temperatureState(undefined), null);
  assert.equal(temperatureState('not-a-temperature'), null);
});
