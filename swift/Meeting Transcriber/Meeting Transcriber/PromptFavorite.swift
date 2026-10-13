import Foundation

nonisolated struct PromptFavorite:
    Identifiable,
    Codable,
    Sendable,
    Equatable
{
    let id: String
    let title: String
    let prompt: String
    let builtIn: Bool
    let category: String

    enum CodingKeys:
        String,
        CodingKey
    {
        case id
        case title
        case prompt
        case builtIn = "built_in"
        case category
    }
}


nonisolated struct PromptFavoritesResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let favorites: [PromptFavorite]

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case favorites
    }
}
