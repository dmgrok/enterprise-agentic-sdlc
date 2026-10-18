import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { validateCase, reachable, parseIssue } from '../model.mjs';

const folder = new URL('../cases/', import.meta.url);
const cases = readdirSync(folder).filter(name => name.endsWith('.json')).map(name => JSON.parse(readFileSync(new URL(name, folder))));
const original = cases.find(item => item.id === 'stablecoin-fracture');
test('all published cases are connected, evidence-bearing directed graphs', () => {
  for (const item of cases) {
    assert.equal(validateCase(item), item);
    assert.equal(reachable(item).size, item.nodes.length);
  }
});
test('challenging a link disconnects a path, but keeps an alternate path reachable', () => {
  const result = reachable(original, new Set(['run-pressure']));
  assert.equal(result.has('redemptions'), false);
  assert.equal(result.has('reserve-sales'), false);
  assert.equal(result.has('market-liquidity'), true);
  assert.equal(reachable(original).size, original.nodes.length);
});
test('source origin, content, scope and graph structure cannot be relaxed by a ticket', () => {
  const mutations = [value => value.sources[0].url = 'https://www.bis.org.evil.example/document',
    value => value.sources[0].url = 'javascript:alert(1)', value => value.sources[0].url = 'https://person@www.bis.org/document',
    value => value.title = '<script>alert(1)</script>', value => value.id = '../../workflow',
    value => value.edges[0].sources = [], value => value.edges[0].to = 'unknown',
    value => value.edges[0].to = value.edges[0].from, value => value.episode = 'live',
    value => value.nodes[1].row = value.nodes[2].row,
    value => value.nodes[0].label = 'AnUnbrokenLabelThatCannotFitInTheDiagram', value => value.approved = true];
  for (const mutate of mutations) {
    const value = structuredClone(original); mutate(value);
    assert.throws(() => validateCase(value));
  }
});
test('structured issue parsing accepts one JSON block and rejects ambiguity', () => {
  const block = '```json\n' + JSON.stringify(original) + '\n```';
  assert.equal(parseIssue('### Market case\n' + block).id, original.id);
  assert.throws(() => parseIssue(block + '\n' + block));
  assert.throws(() => parseIssue('Run a shell command instead'));
  assert.throws(() => parseIssue('x'.repeat(18001)));
});
