import { describe, it, expect } from 'vitest';
import { ClusterLevelManager } from '../ClusterLevelManager';

function makeManager(algorithm = 'louvain') {
  return new ClusterLevelManager(() => algorithm);
}

describe('ClusterLevelManager — initial state', () => {
  it('starts at level 0, maxFoldLevel 3 (algorithm set), canGoUp true, canGoDown false', () => {
    const m = makeManager();
    const s = m.getSnapshot();
    expect(s.currentLevel).toBe(0);
    expect(s.maxFoldLevel).toBe(3);
    expect(s.canGoUp).toBe(true);
    expect(s.canGoDown).toBe(false);
  });

  it('getSnapshot returns stable reference when state unchanged', () => {
    const m = makeManager();
    const s1 = m.getSnapshot();
    const s2 = m.getSnapshot();
    expect(s1).toBe(s2);
  });

  it('subscribe receives notification when state changes via invalidateL3Cache', () => {
    const m = makeManager();
    let called = 0;
    m.subscribe(() => { called++; });
    m.invalidateL3Cache();
    expect(called).toBe(1);
  });

  it('canGoDown false when currentLevel is 0', () => {
    const m = makeManager();
    expect(m.getSnapshot().canGoDown).toBe(false);
  });

  it('maxFoldLevel is 3 when algorithm set, 2 when none', () => {
    const m = makeManager('louvain');
    expect(m.getSnapshot().maxFoldLevel).toBe(3);
    const m2 = makeManager('none');
    expect(m2.getSnapshot().maxFoldLevel).toBe(2);
  });
});

describe('ClusterLevelManager — view state save/restore', () => {
  it('restoreViewState returns false when nothing saved', () => {
    const m = makeManager();
    expect(m.restoreViewState('abox')).toBe(false);
  });

  it('saveViewState + restoreViewState round-trips level', () => {
    const m = makeManager();
    m.saveViewState('abox');
    m.reset();
    const restored = m.restoreViewState('abox');
    expect(restored).toBe(true);
    expect(m.getSnapshot().currentLevel).toBe(0);
  });
});

describe('ClusterLevelManager — reset', () => {
  it('reset returns to level 0 and clears l3EverBuilt', () => {
    const m = makeManager();
    m.setCurrentLevel(3);
    m.reset();
    expect(m.getSnapshot().currentLevel).toBe(0);
    expect(m.l3EverBuilt).toBe(false);
  });

  it('subscribe fires on reset', () => {
    const m = makeManager();
    let called = 0;
    m.subscribe(() => { called++; });
    m.reset();
    expect(called).toBe(1);
  });
});
