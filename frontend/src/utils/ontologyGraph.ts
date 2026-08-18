/**
 * 本体图谱数据转换公共工具。
 * 供 OntologyBuild（AI 构建流程图谱）与 OntologyDetail（构建预览全屏图谱）共用，
 * 保证两处从构建状态（currentState）生成的原始图谱数据结构一致。
 */

/** 名称归一化：trim + 全角括号转半角，用于父子类型名匹配（与后端 _normalize_name 对齐） */
export const normalizeName = (s: string) =>
  (s || '').trim().replace(/（/g, '(').replace(/）/g, ')').replace(/\u3000/g, ' ')

/**
 * 从构建状态构建原始图谱数据（类型节点 + 实体节点 + 边，含父子层级索引）。
 * 节点结构：
 * - 类型节点：{ id: 'et_{idx}', node_type: 'concept', type, color, parent, parentId, children }
 * - 实体节点：{ id: 'ent_{idx}', node_type: 'entity', concept_id, type, color }
 * 边结构：{ source, target, relation }（类型间关系 / instance_of 归属边 / 实体间关系）
 */
export const buildRawGraphDataFromState = (st: any) => {
  if (!st) return { nodes: [], links: [] }

  const nodes: any[] = []
  const links: any[] = []

  // 类型→索引映射（精确名供 instance_of/关系匹配，归一化名供父子匹配）
  const ets = st.entity_types || []
  const typeNameToIdx: Record<string, number> = {}
  const typeNormToIdx: Record<string, number> = {}
  ets.forEach((et: any, idx: number) => {
    typeNameToIdx[et.name] = idx
    typeNormToIdx[normalizeName(et.name)] = idx
    nodes.push({
      id: `et_${idx}`,
      name: et.name,
      node_type: 'concept',
      type: et.name,
      color: et.color || '#409eff',
      description: et.description || '',
      parent: et.parent_entity_type_name || '',
      parentId: '',
      children: [] as string[],
      symbolSize: 50,
      itemStyle: { color: et.color || '#409eff', borderColor: '#333', borderWidth: 2 },
      label: { fontWeight: 'bold' },
    })
  })

  // 计算 parentId 与 children（父子层级索引）
  const typeNodeById: Record<string, any> = {}
  for (const n of nodes) if (n.node_type === 'concept') typeNodeById[n.id] = n
  for (const n of nodes) {
    if (n.node_type !== 'concept') continue
    const pIdx = typeNormToIdx[normalizeName(n.parent)] ?? -1
    if (pIdx >= 0 && `et_${pIdx}` !== n.id) {
      n.parentId = `et_${pIdx}`
      const pNode = typeNodeById[n.parentId]
      if (pNode) pNode.children.push(n.id)
    }
  }

  // 实体节点
  const ents = st.entities || []
  ents.forEach((e: any, idx: number) => {
    const etIdx = typeNameToIdx[e.instance_of] ?? -1
    const conceptId = etIdx >= 0 ? `et_${etIdx}` : ''
    const color = etIdx >= 0 ? (ets[etIdx].color || '#409eff') : '#909399'
    nodes.push({
      id: `ent_${idx}`,
      name: e.name,
      node_type: 'entity',
      concept_id: conceptId,
      type: e.instance_of || '',
      color,
      symbolSize: 32,
      itemStyle: { color, borderColor: '#fff', borderWidth: 1.5 },
    })
  })

  // 类型间关系
  const etRels = st.entity_type_relations || []
  etRels.forEach((r: any) => {
    const srcIdx = typeNameToIdx[r.source_entity_type_name] ?? -1
    const tgtIdx = typeNameToIdx[r.target_entity_type_name] ?? -1
    if (srcIdx >= 0 && tgtIdx >= 0) {
      links.push({ source: `et_${srcIdx}`, target: `et_${tgtIdx}`, relation: r.relation_type || '关联' })
    }
  })

  // 实例归属边（instance_of）
  ents.forEach((e: any, idx: number) => {
    const etIdx = typeNameToIdx[e.instance_of] ?? -1
    if (etIdx >= 0) {
      links.push({ source: `et_${etIdx}`, target: `ent_${idx}`, relation: 'instance_of' })
    }
  })

  // 实例间关系
  const rels = st.relations || []
  const entNameToIdx: Record<string, number> = {}
  ents.forEach((e: any, idx: number) => { entNameToIdx[e.name] = idx })
  rels.forEach((r: any) => {
    const srcIdx = entNameToIdx[r.source] ?? -1
    const tgtIdx = entNameToIdx[r.target] ?? -1
    if (srcIdx >= 0 && tgtIdx >= 0) {
      links.push({ source: `ent_${srcIdx}`, target: `ent_${tgtIdx}`, relation: r.relation_type || '关联' })
    }
  })

  return { nodes, links }
}
