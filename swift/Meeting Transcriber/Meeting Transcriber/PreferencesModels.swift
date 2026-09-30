import Foundation

nonisolated struct AppPreferenceValues:
    Decodable,
    Sendable
{
    let performanceProfile: String
    let outputDir: String
    let archiveDir: String
    let recordingsDir: String
    let llmBackend: String
    let llmModel: String
    let mlxModel: String
    let llmContextSize: Int
    let llmContextMode: String
    let m4aRetentionDays: Int
    let archivedM4aRetentionDays: Int

    enum CodingKeys:
        String,
        CodingKey
    {
        case performanceProfile =
            "performance_profile"
        case outputDir =
            "output_dir"
        case archiveDir =
            "archive_dir"
        case recordingsDir =
            "recordings_dir"
        case llmBackend =
            "llm_backend"
        case llmModel =
            "llm_model"
        case mlxModel =
            "mlx_model"
        case llmContextSize =
            "llm_context_size"
        case llmContextMode =
            "llm_context_mode"
        case m4aRetentionDays =
            "m4a_retention_days"
        case archivedM4aRetentionDays =
            "archived_m4a_retention_days"
    }
}


nonisolated struct BackendOption:
    Identifiable,
    Decodable,
    Sendable
{
    let value: String
    let label: String
    let description: String

    var id: String { value }
}

nonisolated struct ResolvedLLMBackend:
    Decodable,
    Sendable
{
    let requestedName: String
    let resolvedName: String
    let effectiveModel: String
    let reason: String
    let mlxAvailable: Bool
    let autoEligible: Bool

    enum CodingKeys:
        String,
        CodingKey
    {
        case requestedName =
            "requested_name"
        case resolvedName =
            "resolved_name"
        case effectiveModel =
            "effective_model"
        case reason
        case mlxAvailable =
            "mlx_available"
        case autoEligible =
            "auto_eligible"
    }
}

nonisolated struct ContextSizeOption:
    Identifiable,
    Decodable,
    Sendable
{
    let label: String
    let value: Int

    var id: Int { value }
}

nonisolated struct PerformanceProfileOption:
    Identifiable,
    Decodable,
    Sendable
{
    let name: String
    let description: String

    var id: String { name }
}

nonisolated struct HardwareProfileSummary:
    Decodable,
    Sendable
{
    let displayLabel: String
    let chipName: String
    let memoryGB: Int
    let performanceClass: String

    enum CodingKeys:
        String,
        CodingKey
    {
        case displayLabel =
            "display_label"
        case chipName =
            "chip_name"
        case memoryGB =
            "memory_gb"
        case performanceClass =
            "performance_class"
    }
}

nonisolated struct ResolvedPerformanceProfile:
    Decodable,
    Sendable
{
    let requestedName: String
    let resolvedName: String
    let contextSizeTokens: Int
    let directTokenBudget: Int
    let chunkSourceTokenBudget: Int
    let chunkOverlapTokens: Int
    let hardwareLabel: String
    let reason: String
    let contextMode: String
    let contextOverrideTokens: Int

    enum CodingKeys:
        String,
        CodingKey
    {
        case requestedName =
            "requested_name"
        case resolvedName =
            "resolved_name"
        case contextSizeTokens =
            "context_size_tokens"
        case directTokenBudget =
            "direct_token_budget"
        case chunkSourceTokenBudget =
            "chunk_source_token_budget"
        case chunkOverlapTokens =
            "chunk_overlap_tokens"
        case hardwareLabel =
            "hardware_label"
        case reason
        case contextMode =
            "context_mode"
        case contextOverrideTokens =
            "context_override_tokens"
    }
}

nonisolated struct PreferencesResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let settings: AppPreferenceValues
    let backendOptions: [BackendOption]
    let resolvedLLMBackend: ResolvedLLMBackend
    let performanceProfiles: [String]
    let performanceProfileOptions:
        [PerformanceProfileOption]
    let hardwareProfile:
        HardwareProfileSummary
    let resolvedPerformanceProfile:
        ResolvedPerformanceProfile
    let contextSizeOptions:
        [ContextSizeOption]
    let installedModels: [String]
    let modelStatus: String
    let archiveStatus: String
    let modelDiscoveryError: String?

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case settings
        case backendOptions =
            "backend_options"
        case resolvedLLMBackend =
            "resolved_llm_backend"
        case performanceProfiles =
            "performance_profiles"
        case performanceProfileOptions =
            "performance_profile_options"
        case hardwareProfile =
            "hardware_profile"
        case resolvedPerformanceProfile =
            "resolved_performance_profile"
        case contextSizeOptions =
            "context_size_options"
        case installedModels =
            "installed_models"
        case modelStatus =
            "model_status"
        case archiveStatus =
            "archive_status"
        case modelDiscoveryError =
            "model_discovery_error"
    }
}

nonisolated struct SavePreferencesResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let saved: Bool
    let message: String

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case saved
        case message
    }
}
