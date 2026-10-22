import assert from 'node:assert/strict';
import test from 'node:test';
import { shortcutFromEvent } from '../lib/hotkeys.ts';

const stroke = (overrides) => ({ key: '!', code: 'Digit1', ctrlKey: true, shiftKey: true, altKey: false, metaKey: false, ...overrides });
test('Shift+1 uses physical Digit1 instead of !', () => assert.equal(shortcutFromEvent(stroke({})), 'ctrl+shift+1'));
test('OEM keys use supported Windows names', () => assert.equal(shortcutFromEvent(stroke({key: '+', code: 'Equal'})), 'ctrl+shift+equal'));
test('modifier-only input is ignored', () => assert.equal(shortcutFromEvent(stroke({key: 'Control', code: 'ControlLeft'})), null));
test('letter follows physical key even with layout-dependent output', () => assert.equal(shortcutFromEvent(stroke({key: 'á', code: 'KeyA'})), 'ctrl+shift+a'));
test('Escape and arrows are canonical', () => assert.equal(shortcutFromEvent(stroke({key: 'Escape', code: 'Escape', ctrlKey: false, shiftKey: false})), 'esc'));
