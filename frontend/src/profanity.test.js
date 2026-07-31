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

test('censors racial slur variants as complete words', () => {
  assert.equal(censorProfanity('nigga, NIGGER and niggas'), '*****, ****** and ******');
});

test('censors expanded English profanity and common obfuscations', () => {
  assert.equal(
    censorProfanity('damn douchebag prick f*ck a$$hole'),
    '**** ********* ***** **** *******',
  );
});

test('censors Maltese inflections and unaccented keyboard spellings', () => {
  assert.equal(
    censorProfanity('żobbi zobbhom sormok mnieghel pacocc'),
    '***** ******* ****** ******** ******',
  );
});

test('does not censor tit because bird names are valid chat content', () => {
  assert.equal(censorProfanity('A blue tit visited today'), 'A blue tit visited today');
});
