import type {
  ValidationProvider,
  ValidationEvent,
  ValidationResult,
  ValidatedElement,
  ElementIri,
} from '@reactodia/workspace';

const ERROR_PRED = 'urn:vg:reasoningError';
const WARNING_PRED = 'urn:vg:reasoningWarning';

export class RdfValidationProvider implements ValidationProvider {
  private _errorMap = new Map<string, string[]>();
  private _warningMap = new Map<string, string[]>();

  setErrors(map: Map<string, string[]>): void {
    this._errorMap = new Map(map);
  }

  setWarnings(map: Map<string, string[]>): void {
    this._warningMap = new Map(map);
  }

  clearErrors(): void {
    this._errorMap.clear();
    this._warningMap.clear();
  }

  getAffectedIris(): Set<string> {
    const iris = new Set<string>();
    for (const k of this._errorMap.keys()) iris.add(k);
    for (const k of this._warningMap.keys()) iris.add(k);
    return iris;
  }

  async validate(e: ValidationEvent): Promise<ValidationResult> {
    const items: ValidatedElement[] = [];
    const target = e.target.id as ElementIri;
    const propErrors = e.target.properties?.[ERROR_PRED] ?? [];
    const propWarnings = e.target.properties?.[WARNING_PRED] ?? [];
    const injectedErrors = this._errorMap.get(e.target.id as string) ?? [];
    const injectedWarnings = this._warningMap.get(e.target.id as string) ?? [];

    for (const msg of injectedErrors) {
      items.push({ type: 'element', target, severity: 'error', message: msg });
    }
    for (const v of propErrors) {
      items.push({ type: 'element', target, severity: 'error', message: (v as any)?.value ?? 'Reasoning error' });
    }
    for (const msg of injectedWarnings) {
      items.push({ type: 'element', target, severity: 'warning', message: msg });
    }
    for (const v of propWarnings) {
      items.push({ type: 'element', target, severity: 'warning', message: (v as any)?.value ?? 'Reasoning warning' });
    }

    return { items };
  }
}
