/**
 * ClusterLevelManager — owns level state (L0-L3) and group operations.
 *
 * Level switching uses Reactodia's native model.group() / model.ungroupAll():
 *   - Fold (L1→L2, L2→L3): model.group() — groups appear at member centroids
 *   - Unfold (L2→L1, L3→L2): model.ungroupAll() then canvas.animateGraph()
 *     using pre-computed positions from the silent layout worker.
 *
 * Cluster membership per level is saved before any ungroupAll so manual user
 * edits survive level round-trips.
 *
 * Plain class with subscribe/getSnapshot compatible with useSyncExternalStore.
 */

import * as Reactodia from '@reactodia/workspace';
import type { N3DataProvider, ViewMode, CommunityClusterEntry } from '@/providers/N3DataProvider';
import { rerootForCanvas, type StructuralGroupMap, type SubclassParentMap } from './structuralGroups';
import { computeClustersLabelPropagation } from './clusterAlgorithms/labelPropagation';
import { computeClustersLouvainNgraph } from './clusterAlgorithms/louvainNgraph';
import { computeClustersKmeans } from './clusterAlgorithms/kmeans';
import type { ClusterNode, ClusterEdge } from './clusterAlgorithms/types';

export interface ClusterEntry {
  iris: string[];
  position: Reactodia.Vector;
}

export interface LevelSnapshot {
  currentLevel: 0 | 1 | 2 | 3;
  maxFoldLevel: 2 | 3;
  canGoUp: boolean;
  canGoDown: boolean;
}

interface SavedLevelState {
  currentLevel: 0 | 1 | 2 | 3;
  l3EverBuilt: boolean;
  cachedClusterState: ClusterEntry[] | null;
}

export interface PrecomputedPositions {
  l1: Map<string, Reactodia.Vector>;
  l2: Map<string, Reactodia.Vector>;
}

export class ClusterLevelManager {
  private _currentLevel: 0 | 1 | 2 | 3 = 0;
  private _l3EverBuilt = false;
  private _cachedClusterState: ClusterEntry[] | null = null;
  private _savedStateByMode: Partial<Record<ViewMode, SavedLevelState>> = {};

  // L2 structural group membership — saved when L2 groups are created so
  // L3→L2 restoration and level round-trips preserve manual edits.
  private _l2Setup: ClusterEntry[] | null = null;

  // Pre-computed layout positions for L1 (entities) and L2 (structural groups),
  // produced by the silent layout worker after L3 init.
  private _precomputedPositions: PrecomputedPositions | null = null;

  // Positions captured immediately before collapse animation — used to restore
  // node positions on expand when autoApplyLayout is disabled.
  private _savedL1Positions: Map<string, Reactodia.Vector> | null = null;
  private _savedL2Positions: Map<string, Reactodia.Vector> | null = null;

  private _ctx: Reactodia.WorkspaceContext | null = null;
  private _dataProvider: N3DataProvider | null = null;
  private _getClusteringAlgorithm: () => string;

  private _subscribers = new Set<() => void>();
  private _snapshot: LevelSnapshot | null = null;

  constructor(getClusteringAlgorithm: () => string) {
    this._getClusteringAlgorithm = getClusteringAlgorithm;
  }

  init(ctx: Reactodia.WorkspaceContext, dataProvider: N3DataProvider): void {
    this._ctx = ctx;
    this._dataProvider = dataProvider;
  }

  // ── Reactive interface ────────────────────────────────────────────────────

  subscribe = (callback: () => void): (() => void) => {
    this._subscribers.add(callback);
    return () => this._subscribers.delete(callback);
  };

  getSnapshot = (): LevelSnapshot => {
    const algorithm = this._getClusteringAlgorithm();
    const maxFoldLevel: 2 | 3 = (this._l3EverBuilt || algorithm !== 'none') ? 3 : 2;
    const canGoUp =
      this._currentLevel < maxFoldLevel &&
      !(this._currentLevel === 2 && algorithm === 'none');
    const canGoDown = this._currentLevel > 0;

    if (
      this._snapshot &&
      this._snapshot.currentLevel === this._currentLevel &&
      this._snapshot.maxFoldLevel === maxFoldLevel &&
      this._snapshot.canGoUp === canGoUp &&
      this._snapshot.canGoDown === canGoDown
    ) {
      return this._snapshot;
    }

    this._snapshot = { currentLevel: this._currentLevel, maxFoldLevel, canGoUp, canGoDown };
    return this._snapshot;
  };

  private notify(): void {
    this._snapshot = null;
    for (const cb of this._subscribers) {
      try { cb(); } catch { /* ignore */ }
    }
  }

  // ── Read-only accessors ───────────────────────────────────────────────────

  get currentLevel(): 0 | 1 | 2 | 3 { return this._currentLevel; }
  get l3EverBuilt(): boolean { return this._l3EverBuilt; }
  get clusterState(): ReadonlyArray<ClusterEntry> | null { return this._cachedClusterState; }

  shouldAutoCluster(entityCount: number, algorithm: string, threshold: number): boolean {
    return algorithm !== 'none' && entityCount > threshold && !this._l3EverBuilt;
  }

  setCurrentLevel(level: 0 | 1 | 2 | 3): void {
    if (this._currentLevel === level) return;
    this._currentLevel = level;
    this.notify();
  }

  // ── Pre-computed positions (from silent layout worker) ────────────────────

  setPrecomputedPositions(positions: PrecomputedPositions): void {
    this._precomputedPositions = positions;
  }

  hasPositionsForLevel(level: number): boolean {
    if (level === 1) return !!(this._savedL1Positions?.size || this._precomputedPositions?.l1?.size);
    if (level === 2) return !!(this._savedL2Positions?.size || this._precomputedPositions?.l2?.size);
    return false;
  }

  /**
   * Animate expanded elements back to their saved positions.
   * Called from handleLevelDown when autoApplyLayout is OFF — performLayout
   * would normally handle position restoration, but with layout disabled we
   * use the positions snapshotted before collapse instead.
   */
  async animateExpandPositions(): Promise<void> {
    const ctx = this._ctx;
    const model = ctx?.model;
    if (!ctx || !model) return;
    if (this._currentLevel === 1) await this._animateToLevel1(ctx, model);
    else if (this._currentLevel === 2) await this._animateToLevel2(ctx);
  }

  // ── Cluster setup persistence ─────────────────────────────────────────────

  /**
   * Read the current model's EntityGroups and save their membership for the
   * given level. Call BEFORE any ungroupAll so manual edits are preserved.
   */
  saveCurrentSetup(model: Reactodia.DataDiagramModel, level: number): void {
    const groups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    const setup: ClusterEntry[] = groups.map(g => ({
      iris: g.items.map(item => item.data.id as string),
      position: { ...g.position },
    }));
    if (level === 2) {
      this._l2Setup = setup.length > 0 ? setup : null;
    } else if (level === 3) {
      this._cachedClusterState = setup.length > 0 ? setup : null;
    }
  }

  // ── Level navigation ──────────────────────────────────────────────────────

  async levelUp(): Promise<{ needsLayout: boolean }> {
    const ctx = this._ctx;
    const model = ctx?.model;
    if (!ctx || !model) return { needsLayout: false };

    if (this._currentLevel === 0) {
      this._foldL1(model);
      this._currentLevel = 1;
      this.notify();
      return { needsLayout: false };
    }

    if (this._currentLevel === 1) {
      await this._animateCollapseL1toL2(ctx, model);
      this._foldL2(ctx, model);
      this._currentLevel = 2;
      this.notify();
      return { needsLayout: false };
    }

    if (this._currentLevel === 2) {
      const algorithm = this._getClusteringAlgorithm();
      if (algorithm === 'none') return { needsLayout: false };

      // Save L2 groups before any ungroup mutation so round-trips preserve manual edits.
      this.saveCurrentSetup(model, 2);

      // Restore from cached L3 (avoid re-running algorithm and re-layout).
      if (this._cachedClusterState?.length) {
        await this._animateCollapseL2toL3(ctx, model);
        const applied = this._applyCache(model, this._cachedClusterState);
        if (applied) {
          this._cachedClusterState = applied;
          this._l3EverBuilt = true;
          this._currentLevel = 3;
          this.notify();
          return { needsLayout: false };
        }
        this._cachedClusterState = null;
      }

      // Fresh L3 build. Flatten L2 groups first so entities are available.
      this._switchCanvasToL1ForBuild(model);

      const created = this._buildL3(ctx, model, algorithm);
      if (created) {
        this._currentLevel = 3;
        this.notify();
        return { needsLayout: true };
      }
      return { needsLayout: false };
    }

    return { needsLayout: false };
  }

  /** Ungroups whatever groups are on canvas so entities are available for _buildL3. */
  private _switchCanvasToL1ForBuild(model: Reactodia.DataDiagramModel): void {
    const groups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    if (groups.length > 0) model.ungroupAll(groups);
  }

  levelDown(): { needsLayout: boolean } {
    const ctx = this._ctx;
    const model = ctx?.model;
    if (!ctx || !model) return { needsLayout: false };

    if (this._currentLevel === 3) {
      // Save L3 setup before ungrouping so the user's manual group edits survive.
      this.saveCurrentSetup(model, 3);
      this._clearL3(ctx, model);
      this._currentLevel = 2;
      this.notify();
      return { needsLayout: true };
    } else if (this._currentLevel === 2) {
      // Save L2 setup before ungrouping.
      this.saveCurrentSetup(model, 2);
      this._unfoldL2(model);
      this._currentLevel = 1;
      this.notify();
      return { needsLayout: true };
    } else if (this._currentLevel === 1) {
      this._unfoldL1(model);
      this._currentLevel = 0;
      this.notify();
    }
    return { needsLayout: false };
  }

  /**
   * Returns future group member arrays for the next level-up animation preview.
   * Returns null when no grouping would occur.
   */
  previewNextLevelUp(): Array<{ members: Reactodia.EntityElement[] }> | null {
    const ctx = this._ctx;
    const model = ctx?.model;
    if (!ctx || !model) return null;

    if (this._currentLevel === 1) {
      const viewMode = this._dataProvider?.currentViewMode ?? 'abox';
      const result = this._dataProvider?.getStructuralGroupsForView(viewMode);
      const groupMap = result?.groupMap;
      if (!groupMap || groupMap.size === 0) return null;

      const rootToMembers = new Map<string, Set<string>>();
      for (const [memberIri, rootIri] of groupMap) {
        if (!rootToMembers.has(rootIri)) rootToMembers.set(rootIri, new Set());
        rootToMembers.get(rootIri)!.add(memberIri);
      }

      const unpersistedIris = this._getUnpersistedIris(ctx);
      const elementByIri = new Map<string, Reactodia.EntityElement>();
      for (const el of model.elements) {
        if (el instanceof Reactodia.EntityElement && !unpersistedIris.has(el.data.id)) {
          elementByIri.set(el.data.id, el);
        }
      }

      const plans: Array<{ members: Reactodia.EntityElement[] }> = [];
      for (const [rootIri, memberIris] of rootToMembers) {
        const rootEl = elementByIri.get(rootIri);
        if (!rootEl) continue;
        const members: Reactodia.EntityElement[] = [rootEl];
        for (const mIri of memberIris) {
          const el = elementByIri.get(mIri);
          if (el) members.push(el);
        }
        if (members.length >= 2) plans.push({ members });
      }
      return plans.length > 0 ? plans : null;
    }

    if (this._currentLevel === 2) {
      const entityElements = model.elements.filter(
        (el): el is Reactodia.EntityElement => el instanceof Reactodia.EntityElement
      );
      if (entityElements.length < 2) return null;

      let memberGroups: ReadonlyArray<{ iris: string[] }> | null = null;
      if (this._cachedClusterState?.length) {
        memberGroups = this._cachedClusterState;
      } else if (this._dataProvider) {
        const viewMode = this._dataProvider.currentViewMode;
        const allSubjects = new Set(entityElements.map(el => el.data.id as string));
        const providerClusters = this._dataProvider.getCommunityGroups(
          this._getClusteringAlgorithm(), viewMode, allSubjects
        );
        if (providerClusters.length > 0) memberGroups = providerClusters;
      }
      if (!memberGroups) return null;

      const elementByIri = new Map(entityElements.map(el => [el.data.id as string, el]));
      const plans: Array<{ members: Reactodia.EntityElement[] }> = [];
      for (const { iris } of memberGroups) {
        const members = iris
          .map(iri => elementByIri.get(iri))
          .filter((el): el is Reactodia.EntityElement => el !== undefined);
        if (members.length >= 2) plans.push({ members });
      }
      return plans.length > 0 ? plans : null;
    }

    return null;
  }

  // ── Group operations (internal) ───────────────────────────────────────────

  private _foldL1(model: Reactodia.DataDiagramModel): void {
    for (const el of model.elements) {
      if (el instanceof Reactodia.EntityElement) {
        model.history.execute(Reactodia.setElementExpanded(el, false));
      } else if (el instanceof Reactodia.EntityGroup) {
        for (const item of el.items) {
          if (item instanceof Reactodia.EntityElement) {
            model.history.execute(Reactodia.setElementExpanded(item, false));
          }
        }
      }
    }
  }

  private _unfoldL1(model: Reactodia.DataDiagramModel): void {
    for (const el of model.elements) {
      if (el instanceof Reactodia.EntityElement) {
        model.history.execute(Reactodia.setElementExpanded(el, true));
      } else if (el instanceof Reactodia.EntityGroup) {
        for (const item of el.items) {
          if (item instanceof Reactodia.EntityElement) {
            model.history.execute(Reactodia.setElementExpanded(item, true));
          }
        }
      }
    }
  }

  private _foldL2(
    ctx: Reactodia.WorkspaceContext,
    model: Reactodia.DataDiagramModel,
  ): void {
    const viewMode = this._dataProvider?.currentViewMode ?? 'abox';
    const { groupMap, subclassParent } = this._dataProvider?.getStructuralGroupsForView(viewMode)
      ?? { groupMap: new Map(), subclassParent: new Map() };
    const unpersistedIris = this._getUnpersistedIris(ctx);
    const created = applyL2Fold(ctx, model, groupMap, subclassParent, unpersistedIris);
    // Save the freshly created L2 groups so level round-trips restore them.
    if (created > 0) {
      this._l2Setup = model.elements
        .filter((el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup)
        .map(g => ({ iris: g.items.map(item => item.data.id as string), position: { ...g.position } }));
    }
  }

  /** L2→L1: ungroup L2 structural groups. Entities land at group positions. */
  private _unfoldL2(model: Reactodia.DataDiagramModel): void {
    const l2Groups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    model.ungroupAll(l2Groups);
  }

  private _buildL3(
    ctx: Reactodia.WorkspaceContext,
    model: Reactodia.DataDiagramModel,
    algorithm: string
  ): boolean {
    // Capture L2 group membership before ungrouping so L2 members stay together
    const l2Groups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    const l2Membership = new Map<string, Set<string>>();
    const memberToRoot = new Map<string, string>();
    for (const group of l2Groups) {
      const rootIri = group.items[0]?.data.id as string;
      if (!rootIri) continue;
      const members = new Set(group.items.map(item => item.data.id as string));
      l2Membership.set(rootIri, members);
      for (const m of members) memberToRoot.set(m, rootIri);
    }

    if (l2Groups.length) model.ungroupAll(l2Groups);

    const entityElements = model.elements.filter(
      (el): el is Reactodia.EntityElement => el instanceof Reactodia.EntityElement
    );
    const relationLinks = model.links.filter(
      (lk): lk is Reactodia.RelationLink => lk instanceof Reactodia.RelationLink
    );

    if (entityElements.length < 2) return false;

    // Map each entity to its effective super-node ID (L2 root or self)
    const effectiveId = (iri: string) => memberToRoot.get(iri) ?? iri;

    // Build connectivity on the contracted (super-node) graph
    const connectivity = new Map<string, number>();
    const seenEdges = new Set<string>();
    for (const el of entityElements) {
      const eid = effectiveId(el.data.id);
      if (!connectivity.has(eid)) connectivity.set(eid, 0);
    }
    for (const lk of relationLinks) {
      const src = effectiveId(lk.data.sourceId);
      const tgt = effectiveId(lk.data.targetId);
      if (src === tgt) continue;
      const key = `${src}\0${tgt}`;
      if (seenEdges.has(key)) continue;
      seenEdges.add(key);
      connectivity.set(src, (connectivity.get(src) ?? 0) + 1);
      connectivity.set(tgt, (connectivity.get(tgt) ?? 0) + 1);
    }

    // Super-node positions: centroid of L2 members
    const superNodePositions = new Map<string, Reactodia.Vector>();
    const elementByIri = new Map(entityElements.map(el => [el.data.id, el]));
    for (const [rootIri, members] of l2Membership) {
      const memberEls = [...members]
        .map(m => elementByIri.get(m))
        .filter((el): el is Reactodia.EntityElement => el !== undefined);
      if (memberEls.length > 0) {
        superNodePositions.set(rootIri, computeCentroid(memberEls));
      }
    }

    // Build deduplicated node/edge lists for the super-node graph
    const processedIds = new Set<string>();
    const clusterNodes: ClusterNode[] = [];
    for (const el of entityElements) {
      const eid = effectiveId(el.data.id);
      if (processedIds.has(eid)) continue;
      processedIds.add(eid);
      clusterNodes.push({
        id: eid,
        connectivity: connectivity.get(eid) ?? 0,
        position: superNodePositions.get(eid) ?? { x: el.position.x, y: el.position.y },
      });
    }

    const clusterEdges: ClusterEdge[] = [];
    const edgeSet = new Set<string>();
    for (const lk of relationLinks) {
      const src = effectiveId(lk.data.sourceId);
      const tgt = effectiveId(lk.data.targetId);
      if (src === tgt) continue;
      const key = `${src}\0${tgt}`;
      if (edgeSet.has(key)) continue;
      edgeSet.add(key);
      clusterEdges.push({ id: lk.id, source: src, target: tgt });
    }

    const { clusters } = selectAlgorithm(algorithm, clusterNodes, clusterEdges, { threshold: 2 });
    if (clusters.size === 0) return false;

    // Expand super-node cluster assignments back to individual entities
    const alreadyGrouped = new Set<string>();
    const newCache: ClusterEntry[] = [];

    for (const [, clusterInfo] of clusters) {
      const members: Reactodia.EntityElement[] = [];
      for (const nodeId of clusterInfo.nodeIds) {
        const expandedIris = l2Membership.get(nodeId) ?? new Set([nodeId]);
        for (const iri of expandedIris) {
          if (alreadyGrouped.has(iri)) continue;
          const el = elementByIri.get(iri);
          if (el) members.push(el);
        }
      }
      if (members.length < 2) continue;
      for (const m of members) alreadyGrouped.add(m.data.id);

      const group = model.group(members);
      const centroid = computeCentroid(members);
      group.setPosition(centroid);
      newCache.push({ iris: members.map(m => m.data.id), position: { ...centroid } });
    }

    if (newCache.length === 0) return false;
    this._cachedClusterState = newCache;
    this._l3EverBuilt = true;
    return true;
  }

  private _applyCache(
    model: Reactodia.DataDiagramModel,
    cache: ReadonlyArray<{ iris: string[]; position?: Reactodia.Vector }>
  ): ClusterEntry[] | null {
    const existingGroups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    if (existingGroups.length) model.ungroupAll(existingGroups);

    const elementByIri = new Map(
      model.elements
        .filter((el): el is Reactodia.EntityElement => el instanceof Reactodia.EntityElement)
        .map(el => [el.data.id, el])
    );

    const applied: ClusterEntry[] = [];
    const alreadyGrouped = new Set<string>();
    for (const { iris, position } of cache) {
      const members = iris
        .map(iri => elementByIri.get(iri))
        .filter((el): el is Reactodia.EntityElement => el !== undefined && !alreadyGrouped.has(el.data.id));
      if (members.length < 2) continue;
      for (const m of members) alreadyGrouped.add(m.data.id);
      const groupPos = position ?? computeCentroid(members);
      const group = model.group(members);
      group.setPosition(groupPos);
      applied.push({ iris: members.map(m => m.data.id), position: { ...groupPos } });
    }

    return applied.length > 0 ? applied : null;
  }

  /** L3→L2: ungroup L3 groups, rebuild L2 from saved setup or structural groups. */
  private _clearL3(ctx: Reactodia.WorkspaceContext, model: Reactodia.DataDiagramModel): void {
    const l3Groups = model.elements.filter(
      (el): el is Reactodia.EntityGroup => el instanceof Reactodia.EntityGroup
    );
    model.ungroupAll(l3Groups);
    this._rebuildL2(ctx, model);
  }

  /**
   * Recreate L2 groups from the saved setup (preserves manual edits) or from
   * structural groups as fallback.
   */
  private _rebuildL2(ctx: Reactodia.WorkspaceContext, model: Reactodia.DataDiagramModel): void {
    if (this._l2Setup?.length) {
      this._applyCache(model, this._l2Setup);
      return;
    }
    const viewMode = this._dataProvider?.currentViewMode ?? 'abox';
    const { groupMap, subclassParent } = this._dataProvider?.getStructuralGroupsForView(viewMode)
      ?? { groupMap: new Map(), subclassParent: new Map() };
    const unpersistedIris = this._getUnpersistedIris(ctx);
    applyL2Fold(ctx, model, groupMap, subclassParent, unpersistedIris);
  }

  /** Animate entities toward structural group centroids before L1→L2 grouping. */
  private async _animateCollapseL1toL2(
    ctx: Reactodia.WorkspaceContext,
    model: Reactodia.DataDiagramModel,
  ): Promise<void> {
    const canvas = ctx.view.findAnyCanvas();
    if (!canvas) return;

    // Snapshot before animation moves entities — used to restore on expand.
    this._savedL1Positions = new Map(
      model.elements
        .filter((el): el is Reactodia.EntityElement => el instanceof Reactodia.EntityElement)
        .map(el => [el.data.id as string, { ...el.position }])
    );

    const viewMode = this._dataProvider?.currentViewMode ?? 'abox';
    const groupMap = this._dataProvider?.getStructuralGroupsForView(viewMode)?.groupMap ?? new Map();
    const unpersistedIris = this._getUnpersistedIris(ctx);

    const rootToMembers = new Map<string, Reactodia.EntityElement[]>();
    for (const el of model.elements) {
      if (!(el instanceof Reactodia.EntityElement) || unpersistedIris.has(el.data.id)) continue;
      const iri = el.data.id as string;
      const rootIri = groupMap.get(iri) ?? iri;
      if (!rootToMembers.has(rootIri)) rootToMembers.set(rootIri, []);
      rootToMembers.get(rootIri)!.push(el);
    }

    const targets: Array<{ members: Reactodia.EntityElement[]; cx: number; cy: number }> = [];
    for (const [, members] of rootToMembers) {
      if (members.length < 2) continue;
      targets.push({
        members,
        cx: members.reduce((s, m) => s + m.position.x, 0) / members.length,
        cy: members.reduce((s, m) => s + m.position.y, 0) / members.length,
      });
    }
    if (targets.length === 0) return;

    canvas.renderingState.syncUpdate();
    await canvas.animateGraph(() => {
      for (const { members, cx, cy } of targets) {
        for (const m of members) m.setPosition({ x: cx, y: cy });
      }
    });
  }

  /** Animate L2 groups toward L3 cluster centroids before L2→L3 grouping. */
  private async _animateCollapseL2toL3(
    ctx: Reactodia.WorkspaceContext,
    model: Reactodia.DataDiagramModel,
  ): Promise<void> {
    const canvas = ctx.view.findAnyCanvas();
    const state = this._cachedClusterState;
    if (!canvas || !state?.length) return;

    // Snapshot ALL L2 element positions (groups and standalone entities)
    // so the full set can be restored when navigating back down to L2.
    const savedL2 = new Map<string, Reactodia.Vector>();
    for (const el of model.elements) {
      if (el instanceof Reactodia.EntityGroup) {
        const firstItem = el.items[0];
        if (firstItem) savedL2.set(firstItem.data.id as string, { ...el.position });
      } else if (el instanceof Reactodia.EntityElement) {
        savedL2.set(el.data.id as string, { ...el.position });
      }
    }
    this._savedL2Positions = savedL2;

    // Map entity IRI → its L2 EntityGroup
    const entityToGroup = new Map<string, Reactodia.EntityGroup>();
    for (const el of model.elements) {
      if (!(el instanceof Reactodia.EntityGroup)) continue;
      for (const item of el.items) {
        entityToGroup.set(item.data.id as string, el);
      }
    }

    // For each L3 cluster: collect the L2 groups it will merge and their centroid
    const targets: Array<{ groups: Set<Reactodia.EntityGroup>; cx: number; cy: number }> = [];
    for (const { iris } of state) {
      const groups = new Set<Reactodia.EntityGroup>();
      for (const iri of iris) {
        const g = entityToGroup.get(iri);
        if (g) groups.add(g);
      }
      if (groups.size < 2) continue;
      const positions = [...groups].map(g => g.position);
      targets.push({
        groups,
        cx: positions.reduce((s, p) => s + p.x, 0) / positions.length,
        cy: positions.reduce((s, p) => s + p.y, 0) / positions.length,
      });
    }
    if (targets.length === 0) return;

    canvas.renderingState.syncUpdate();
    await canvas.animateGraph(() => {
      for (const { groups, cx, cy } of targets) {
        for (const g of groups) g.setPosition({ x: cx, y: cy });
      }
    });
  }

  /** Animate L2 elements to saved/pre-computed positions after L3→L2 transition. */
  private async _animateToLevel2(ctx: Reactodia.WorkspaceContext): Promise<void> {
    const canvas = ctx.view.findAnyCanvas();
    const l2Positions = this._savedL2Positions ?? this._precomputedPositions?.l2;
    if (!canvas || !l2Positions?.size) return;
    canvas.renderingState.syncUpdate();
    await canvas.animateGraph(() => {
      for (const el of ctx.model.elements) {
        if (el instanceof Reactodia.EntityGroup) {
          const firstItem = el.items[0];
          const key = firstItem?.data.id as string | undefined;
          const pos = key ? l2Positions.get(key) : undefined;
          if (pos) el.setPosition(pos);
        } else if (el instanceof Reactodia.EntityElement) {
          const iri = el.data.id as string;
          const pos = l2Positions.get(iri);
          if (pos) el.setPosition(pos);
        }
      }
    });
  }

  /** Animate entities to saved/pre-computed positions after L2→L1 transition. */
  private async _animateToLevel1(
    ctx: Reactodia.WorkspaceContext,
    model: Reactodia.DataDiagramModel,
  ): Promise<void> {
    const canvas = ctx.view.findAnyCanvas();
    const l1Positions = this._savedL1Positions ?? this._precomputedPositions?.l1;
    if (!canvas || !l1Positions?.size) return;
    canvas.renderingState.syncUpdate();
    await canvas.animateGraph(() => {
      for (const el of model.elements) {
        if (!(el instanceof Reactodia.EntityElement)) continue;
        const pos = l1Positions.get(el.data.id as string);
        if (pos) el.setPosition(pos);
      }
    });
  }

  private _getUnpersistedIris(ctx: Reactodia.WorkspaceContext): Set<string> {
    const result = new Set<string>();
    const editor = ctx.editor;
    if (!editor?.authoringState?.elements) return result;
    for (const [iri, event] of editor.authoringState.elements) {
      if (event.type === 'entityAdd') result.add(iri);
    }
    return result;
  }

  // ── L3 cache management ───────────────────────────────────────────────────

  snapshotClusterPositions(): void {
    const model = this._ctx?.model;
    if (!model || !this._cachedClusterState) return;
    const iriToGroupPos = new Map<string, Reactodia.Vector>();
    for (const el of model.elements) {
      if (!(el instanceof Reactodia.EntityGroup)) continue;
      const firstItem = el.items[0];
      if (firstItem) {
        iriToGroupPos.set(firstItem.data.id as string, { ...el.position });
      }
    }
    for (const entry of this._cachedClusterState) {
      const firstIri = entry.iris[0];
      if (!firstIri) continue;
      const groupPos = iriToGroupPos.get(firstIri);
      if (groupPos) entry.position = groupPos;
    }
  }

  invalidateL3Cache(): void {
    this._cachedClusterState = null;
    this._l3EverBuilt = false;
    this._snapshot = null;
    this._dataProvider?.invalidateCommunityGroups();
    this.notify();
  }

  buildL3(algorithm: string, allSubjects?: Iterable<string>): { needsLayout: boolean } {
    const ctx = this._ctx;
    const model = ctx?.model;
    if (!ctx || !model) return { needsLayout: false };

    // 1. Per-view cache
    if (this._cachedClusterState?.length) {
      const applied = this._applyCache(model, this._cachedClusterState);
      if (applied) {
        this._cachedClusterState = applied;
        this._l3EverBuilt = true;
        this._currentLevel = 3;
        this.notify();
        return { needsLayout: true };
      }
      this._cachedClusterState = null;
    }

    // 2. Provider topology clusters
    if (this._dataProvider && allSubjects) {
      const viewMode = this._dataProvider.currentViewMode;
      const providerClusters: CommunityClusterEntry[] =
        this._dataProvider.getCommunityGroups(algorithm, viewMode, allSubjects);
      if (providerClusters.length > 0) {
        const applied = this._applyCache(model, providerClusters);
        if (applied) {
          this._cachedClusterState = applied;
          this._l3EverBuilt = true;
          this._currentLevel = 3;
          this.notify();
          return { needsLayout: true };
        }
      }
    }

    // 3. Fresh computation
    const created = this._buildL3(ctx, model, algorithm);
    if (created) {
      this._currentLevel = 3;
      this.notify();
      return { needsLayout: true };
    }

    return { needsLayout: false };
  }

  // ── View-mode persistence ─────────────────────────────────────────────────

  saveViewState(mode: ViewMode): void {
    this._savedStateByMode[mode] = {
      currentLevel: this._currentLevel,
      l3EverBuilt: this._l3EverBuilt,
      cachedClusterState: this._cachedClusterState,
    };
  }

  restoreViewState(mode: ViewMode): boolean {
    const saved = this._savedStateByMode[mode];
    if (!saved) return false;
    this._currentLevel = saved.currentLevel;
    this._l3EverBuilt = saved.l3EverBuilt;
    this._cachedClusterState = saved.cachedClusterState;
    this.notify();
    return true;
  }

  reset(): void {
    this._currentLevel = 0;
    this._l3EverBuilt = false;
    this._l2Setup = null;
    this._precomputedPositions = null;
    this._savedL1Positions = null;
    this._savedL2Positions = null;
    this._cachedClusterState = null;
    this.notify();
  }

  resetViewHistory(): void {
    this._savedStateByMode = {};
  }
}

// ── Module-scope utilities (also exported for groupingUtils) ──────────────────

export function applyL2Fold(
  ctx: Reactodia.WorkspaceContext,
  model: Reactodia.DataDiagramModel,
  groupMap: StructuralGroupMap,
  subclassParent: SubclassParentMap,
  unpersistedIris: ReadonlySet<string>
): number {
  if (groupMap.size === 0) return 0;

  const elementByIri = new Map<string, Reactodia.EntityElement>();
  for (const el of model.elements) {
    if (el instanceof Reactodia.EntityElement && !unpersistedIris.has(el.data.id)) {
      elementByIri.set(el.data.id, el);
    }
  }

  const onCanvas = new Set(elementByIri.keys());
  const effectiveMap = rerootForCanvas(groupMap, subclassParent, onCanvas);

  const rootToMembers = new Map<string, Set<string>>();
  for (const [memberIri, rootIri] of effectiveMap) {
    if (!rootToMembers.has(rootIri)) rootToMembers.set(rootIri, new Set());
    rootToMembers.get(rootIri)!.add(memberIri);
  }

  const alreadyGrouped = new Set<string>();
  let groupsCreated = 0;
  for (const [rootIri, memberIris] of rootToMembers) {
    const rootEl = elementByIri.get(rootIri);
    if (!rootEl || alreadyGrouped.has(rootIri)) continue;
    const members: Reactodia.EntityElement[] = [rootEl];
    for (const mIri of memberIris) {
      if (alreadyGrouped.has(mIri)) continue;
      const el = elementByIri.get(mIri);
      if (el) members.push(el);
    }
    if (members.length < 2) continue;
    for (const m of members) alreadyGrouped.add(m.data.id);
    ctx.model.group(members);
    groupsCreated++;
  }
  return groupsCreated;
}

export function getUnpersistedIris(ctx: Reactodia.WorkspaceContext): Set<string> {
  const result = new Set<string>();
  const editor = ctx.editor;
  if (!editor?.authoringState?.elements) return result;
  for (const [iri, event] of editor.authoringState.elements) {
    if (event.type === 'entityAdd') result.add(iri);
  }
  return result;
}

function computeCentroid(elements: Reactodia.EntityElement[]): Reactodia.Vector {
  if (elements.length === 0) return { x: 0, y: 0 };
  let x = 0, y = 0;
  for (const el of elements) { x += el.position.x; y += el.position.y; }
  return { x: x / elements.length, y: y / elements.length };
}

function selectAlgorithm(
  algorithm: string,
  nodes: ClusterNode[],
  edges: ClusterEdge[],
  options: { threshold: number }
): ReturnType<typeof computeClustersLabelPropagation> {
  switch (algorithm) {
    case 'louvain':           return computeClustersLouvainNgraph(nodes, edges, options);
    case 'label-propagation': return computeClustersLabelPropagation(nodes, edges, options);
    case 'kmeans':            return computeClustersKmeans(nodes, edges, options);
    default:                  return computeClustersLabelPropagation(nodes, edges, options);
  }
}
