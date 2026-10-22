import assert from 'node:assert/strict';
import test from 'node:test';
import { SpeechPlayer } from '../lib/speech-player.ts';
const tick = () => new Promise(resolve => setImmediate(resolve));
function audio(overrides = {}) {
  return { duration: 0.01, onended:null, onpause:null, onerror:null, onloadedmetadata:null,
    play: async function() { this.onended?.(); }, pause() {}, ...overrides };
}
test('changing voices between sessions still plays the next audio', async () => {
  const urls = []; const player = new SpeechPlayer(url => {urls.push(url); return audio();});
  await player.enqueue('adam','default'); player.stop(); await player.enqueue('heart','default');
  assert.deepEqual(urls,['adam','heart']);
});
test('stop during slow output selection cannot wedge the new session', async () => {
  let release; let oldPlayed = false; let newPlayed = false;
  const player = new SpeechPlayer(url => url === 'old' ? audio({setSinkId: () => new Promise(resolve => {release=resolve;}), play:async () => {oldPlayed=true;}}) : audio({play:async function(){newPlayed=true;this.onended?.();}}));
  const old = player.enqueue('old','headphones').catch(error => error.name);
  player.stop(); await player.enqueue('new','default'); release(); await tick();
  assert.equal(await old,'AbortError'); assert.equal(oldPlayed,false); assert.equal(newPlayed,true);
});
test('autoplay error is reported and does not block the next voice', async () => {
  const player = new SpeechPlayer(url => url === 'bad' ? audio({play:async () => {throw new Error('autoplay denied');}}) : audio());
  await assert.rejects(player.enqueue('bad','default'),/autoplay denied/);
  await player.enqueue('good','default');
});
test('output selection error is explicit, no silent speaker fallback', async () => {
  const player = new SpeechPlayer(() => audio());
  await assert.rejects(player.enqueue('test','CABLE'),/cannot select audio output/);
});
test('jobs play sequentially and meter cleanup runs for each', async () => {
  let cleaned = 0; const played = [];
  const player = new SpeechPlayer(url => {played.push(url);return audio();}, () => () => {cleaned++;});
  await Promise.all([player.enqueue('1','default'),player.enqueue('2','default')]);
  assert.deepEqual(played,['1','2']); assert.equal(cleaned,2);
});

test('Chromium natural pause before ended is not a playback failure', async () => {
  const player = new SpeechPlayer(() => audio({ended:false, play:async function(){this.ended=true;this.onpause?.();this.onended?.();}}));
  await player.enqueue('heart','default');
  await player.enqueue('next','default');
});
