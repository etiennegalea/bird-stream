import test from 'node:test';
import assert from 'node:assert/strict';

import { censorProfanity } from './profanity.js';

test('censors English profanity while preserving punctuation', () => {
  assert.equal(censorProfanity('What the fuck, this is bullshit!'), 'What the ****, this is ********!');
});

test('censors accented and keyboard-spelled Maltese profanity', () => {
  assert.equal(censorProfanity('qaħba qahba żobb zobb'), '***** ***** **** ****');
});

test('does not censor profanity embedded inside another word', () => {
  assert.equal(censorProfanity('Scunthorpe and classic'), 'Scunthorpe and classic');
});

test('preserves case-insensitive matching and masks full variants', () => {
  assert.equal(censorProfanity('FUCKING Shit'), '******* ****');
});
