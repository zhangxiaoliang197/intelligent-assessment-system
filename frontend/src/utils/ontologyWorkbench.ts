import type { OntologyDocument } from '@/services/ontologyWorkbench'

export type WorkbenchSelection = { kind: 'type' | 'entity' | 'type-relation' | 'relation'; id: string }
export const cloneDocument = <T>(document: T): T => JSON.parse(JSON.stringify(document))

export function createGraph(document: OntologyDocument, mode: string, clustered: boolean, inferences: any[] = []) {
  const types = document.entity_types || []
  const entities = document.entities || []
  const typeMap = new Map(types.map(item => [item.id, item]))
  const colors = ['#5179ef', '#18a899', '#a16ada', '#e8a43d', '#d96887', '#57a2c8']
  const nodes: any[] = []
  const links: any[] = []
  const includeTypes = mode !== 'instances'
  const includeEntities = mode !== 'types' && !clustered
  const depth = (id: string, seen = new Set<string>()): number => {
    if (seen.has(id)) return 0
    seen.add(id)
    const parent = typeMap.get(id)?.parent_entity_type_id
    return parent && typeMap.has(parent) ? 1 + depth(parent, seen) : 0
  }
  if (includeTypes) types.forEach((item, index) => {
    const count = entities.filter(entity => entity.instance_of === item.id).length
    nodes.push({ ...item, id: item.id, name: item.name, kind: 'type', category: index,
      symbol: 'roundRect', symbolSize: [104, 46],
      itemStyle: { color: item.color || colors[index % colors.length], borderColor: '#fff', borderWidth: 2, shadowColor: '#1d35541a', shadowBlur: 9 },
      label: { color: '#fff', fontWeight: 600, formatter: clustered && count ? `${item.name}\n${count} 个实例` : item.name },
      x: 100 + depth(item.id) * 205, y: 80 + index * 105,
    })
    if (item.parent_entity_type_id) links.push({ id: `parent_${item.id}`, source: item.id, target: item.parent_entity_type_id, relation: '继承', kind: 'hierarchy', lineStyle: { color: '#8fa3bf', type: 'dashed' } })
  })
  if (includeEntities) entities.forEach((item, index) => {
    const type = typeMap.get(item.instance_of)
    const typeIndex = Math.max(0, types.findIndex(type => type.id === item.instance_of))
    const siblings = entities.filter(entity => entity.instance_of === item.instance_of)
    const siblingIndex = siblings.findIndex(entity => entity.id === item.id)
    nodes.push({ ...item, id: item.id, name: item.name, kind: 'entity', category: typeIndex,
      symbol: 'circle', symbolSize: 36,
      itemStyle: { color: type?.color || colors[typeIndex % colors.length], borderColor: '#fff', borderWidth: 2 },
      label: { position: 'bottom', color: '#425674', fontSize: 11 },
      x: includeTypes ? 170 + (depth(type?.id || '') + 1) * 205 : 100 + (index % 6) * 160,
      y: includeTypes ? 80 + typeIndex * 105 + siblingIndex * 57 : 80 + Math.floor(index / 6) * 95,
    })
    if (includeTypes && item.instance_of) links.push({ id: `instance_${item.id}`, source: item.id, target: item.instance_of, relation: '实例属于', kind: 'instance', lineStyle: { color: '#cbd6e3', width: 1 } })
  })
  if (includeTypes) for (const item of document.entity_type_relations || []) {
    links.push({ id: item.id, source: item.source_entity_type_id, target: item.target_entity_type_id, relation: item.relation_type, kind: 'type-relation', lineStyle: { color: '#7e95b3', width: 1.6 } })
  }
  if (includeEntities) for (const item of document.relations || []) {
    links.push({ id: item.id, source: item.source_id, target: item.target_id, relation: item.relation_type, kind: 'relation', lineStyle: { color: '#91a6bf', width: 1.4 } })
  }
  const visibleIds = new Set(nodes.map(node => node.id))
  for (const inference of inferences) {
    links.push({ ...inference, kind: 'inference', lineStyle: { color: '#cc963a', type: 'dashed', width: 2 }, label: { color: '#ac7d30' } })
  }
  return { nodes, links: links.filter(link => visibleIds.has(link.source) && visibleIds.has(link.target)) }
}
