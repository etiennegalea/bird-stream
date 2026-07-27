import test from 'node:test';
import assert from 'node:assert/strict';

import { formatChatTime } from './chatTime.js';

test('formats chat timestamps in 24-hour time without a day period', () => {
  const timestamp = new Date(2026, 6, 27, 21, 5).getTime();
  const formatted = formatChatTime(timestamp, 'en-US');

  assert.equal(formatted, '21:05');
  assert.doesNotMatch(formatted, /AM|PM/i);
});
