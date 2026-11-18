/**
 * Lightweight graph validation helper.
 *
 * The fat map (availableClasses/availableProperties) has been removed.
 * This function now always returns an empty array.
 */

type ValidationError = {
  nodeId: string;
  message: string;
  severity: "error" | "warning";
};

export function validateGraph(
  _nodes: Array<any> = [],
  _edges: Array<any> = [],
): ValidationError[] {
  return [];
}

export default validateGraph;
