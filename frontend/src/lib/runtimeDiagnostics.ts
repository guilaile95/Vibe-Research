// Strict export contract: never forward an unknown field from a newer/invalid server.
type Validator = (value: unknown) => unknown;
const invalid = (): never => { throw new Error("Invalid diagnostics contract"); };
const choice = (...values: unknown[]): Validator => value => values.includes(value) ? value : invalid();
const shape = (fields: Record<string, Validator>): Validator => value => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return invalid();
  const object = value as Record<string, unknown>;
  if (Object.keys(object).length !== Object.keys(fields).length) return invalid();
  return Object.fromEntries(Object.entries(fields).map(([key, validate]) => {
    if (!Object.prototype.hasOwnProperty.call(object, key)) return invalid();
    return [key, validate(object[key])];
  }));
};
const sequence = (validators: Validator[]): Validator => value => {
  if (!Array.isArray(value) || value.length !== validators.length) return invalid();
  return validators.map((validate, i) => validate(value[i]));
};
const port: Validator = value => value === null || (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 65535) ? value : invalid();
const configNames = ["VR_AGENT_RUNTIME_URL", "VR_AGENT_RUNTIME_PORT", "VR_DATA_DIR", "VR_REPORTS_DIR", "VR_API_KEY", "HITHINK_FINANCE_API_KEY", "TUSHARE_TOKEN", "VR_SEC_CONTACT", "VIBE_NATIVE_INTEL_DISABLE_STARTUP_FETCH", "VIBE_NATIVE_INTEL_DISABLE_SCHEDULER"];
const capability = (name: string, ...configuration: string[]) => shape({
  capability: choice(name), configuration: choice(...configuration), verification: choice("NOT_EVALUATED"),
});
const directory = choice("LINK_NOT_INSPECTED", "NOT_DIRECTORY", "ACCESS_CHECK_OK", "ACCESS_CHECK_FAILED", "MISSING", "UNAVAILABLE");

const validateReport = shape({
  schema: choice("runtime_diagnostics.v1"),
  mode: choice("READ_ONLY_NO_PROBES"),
  startup: shape({
    service: choice("vibe-research-api"),
    version: value => typeof value === "string" && /^(?:unknown|[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.+-]+)?)$/.test(value) && value.length <= 64 ? value : invalid(),
    git_sha: value => value === null || (typeof value === "string" && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(value)) ? value : invalid(),
    source_state: choice("clean", "modified", "unknown"),
  }),
  agent_runtime: shape({
    backend_target_port: value => value === 0 ? invalid() : port(value),
    backend_target_provenance: choice("VR_AGENT_RUNTIME_URL", "DEFAULT"),
    declared_runtime_port: port,
    declared_runtime_port_provenance: choice("VR_AGENT_RUNTIME_PORT", "DEFAULT"),
    configuration_status: choice("INVALID_CONFIGURATION", "DYNAMIC_PORT_UNVERIFIED", "PORTS_MATCH", "PORT_MISMATCH"),
    declaration_scope: choice("BACKEND_PROCESS_ENVIRONMENT_NOT_RUNNING_SIDECAR"),
    availability: choice("NOT_EVALUATED"), probe_performed: choice(false),
  }),
  configuration_presence: sequence(configNames.map(name => shape({ name: choice(name), present: choice(true, false) }))),
  directories: shape({ data: directory, reports: directory, write_verification: choice("NOT_EVALUATED") }),
  source_capabilities: sequence([
    capability("public_market_adapters", "BUILTIN"),
    capability("hithink", "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED", "ENV_NAME_ABSENT"),
    capability("tushare", "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED", "ENV_NAME_ABSENT"),
    capability("sec", "ENV_NAME_PRESENT_VALUE_NOT_INSPECTED", "PRIVATE_SETTINGS_NOT_INSPECTED"),
    capability("model_provider", "PRIVATE_SETTINGS_NOT_INSPECTED"),
    capability("native_intel_sources", "PRIVATE_SETTINGS_NOT_INSPECTED"),
  ]),
  limitations: sequence(["ENV_PRESENCE_IS_NOT_VALIDITY", "DECLARED_PORT_IS_NOT_LISTENING_PORT", "DIRECTORY_ACCESS_IS_NOT_WRITE_VERIFICATION", "NO_CREDENTIAL_OR_USER_DATA_READS"].map(value => choice(value))),
});


export function parseRuntimeDiagnostics(value: unknown): unknown {
  const report = validateReport(value) as { agent_runtime: {
    backend_target_port: number | null; declared_runtime_port: number | null; configuration_status: string;
  } };
  const { backend_target_port: target, declared_runtime_port: declared, configuration_status: state } = report.agent_runtime;
  const valid = state === "INVALID_CONFIGURATION" ? target === null || declared === null
    : state === "DYNAMIC_PORT_UNVERIFIED" ? target !== null && declared === 0
      : target !== null && declared !== null && declared > 0
        && (state === "PORTS_MATCH" ? target === declared : target !== declared);
  if (!valid) return invalid();
  return report;
}
