import Combine
import Foundation

@MainActor
final class PromptFavoritesController:
    ObservableObject
{
    @Published
    private(set) var favorites:
        [PromptFavorite] = []

    @Published
    private(set) var isLoading =
        false

    @Published
    var errorMessage: String?

    private let backend =
        BackendService()

    private var hasLoaded = false

    var builtIns:
        [PromptFavorite]
    {
        favorites.filter(\.builtIn)
    }

    var customFavorites:
        [PromptFavorite]
    {
        favorites.filter {
            !$0.builtIn
        }
    }

    func loadIfNeeded() async {
        guard !hasLoaded else {
            return
        }

        await reload()
    }

    func reload() async {
        guard !isLoading else {
            return
        }

        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            favorites =
                try await backend
                    .loadPromptFavorites()
            hasLoaded = true

        } catch {
            errorMessage =
                error.localizedDescription
        }
    }

    func upsertCustom(
        id: String?,
        title: String,
        prompt: String
    ) async -> Bool {
        let cleanTitle =
            title.trimmingCharacters(
                in:
                    .whitespacesAndNewlines
            )

        let cleanPrompt =
            prompt.trimmingCharacters(
                in:
                    .whitespacesAndNewlines
            )

        guard
            !cleanTitle.isEmpty,
            !cleanPrompt.isEmpty
        else {
            errorMessage =
                "Enter both a title and a prompt."
            return false
        }

        var custom =
            customFavorites

        let favoriteID =
            id
            ?? "custom.\(UUID().uuidString)"

        let favorite =
            PromptFavorite(
                id: favoriteID,
                title: cleanTitle,
                prompt: cleanPrompt,
                builtIn: false,
                category: "favorite"
            )

        if let index =
            custom.firstIndex(
                where: {
                    $0.id == favoriteID
                }
            ) {
            custom[index] =
                favorite
        } else {
            custom.append(
                favorite
            )
        }

        return await saveCustom(
            custom
        )
    }

    func deleteCustom(
        id: String
    ) async -> Bool {
        let custom =
            customFavorites.filter {
                $0.id != id
            }

        return await saveCustom(
            custom
        )
    }

    private func saveCustom(
        _ custom:
            [PromptFavorite]
    ) async -> Bool {
        guard !isLoading else {
            return false
        }

        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            favorites =
                try await backend
                    .savePromptFavorites(
                        customFavorites:
                            custom
                    )
            hasLoaded = true
            return true

        } catch {
            errorMessage =
                error.localizedDescription
            return false
        }
    }
}
