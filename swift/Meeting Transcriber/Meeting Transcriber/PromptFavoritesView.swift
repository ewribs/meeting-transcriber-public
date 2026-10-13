import SwiftUI

struct PromptFavoritesBar: View {
    @EnvironmentObject
    private var controller:
        PromptFavoritesController

    @Binding
    var promptText: String

    var onSelect:
        ((PromptFavorite) -> Void)? =
            nil

    @State
    private var showingManager =
        false

    var body: some View {
        VStack(
            alignment: .leading,
            spacing: 8
        ) {
            HStack(spacing: 6) {
                Image(
                    systemName: "star.fill"
                )
                .font(.caption)
                .foregroundStyle(
                    .secondary
                )

                Text("Favorites")
                    .font(.subheadline)
                    .fontWeight(
                        .semibold
                    )

                Spacer()

                Button("Manage…") {
                    showingManager =
                        true
                }
                .buttonStyle(.borderless)
                .controlSize(.small)
            }

            if controller.isLoading
                && controller
                    .favorites.isEmpty {
                ProgressView()
                    .controlSize(.small)

            } else {
                ScrollView(
                    .horizontal,
                    showsIndicators: false
                ) {
                    HStack(spacing: 8) {
                        ForEach(
                            controller.favorites
                        ) { favorite in
                            Button {
                                promptText =
                                    favorite
                                        .prompt

                                onSelect?(
                                    favorite
                                )
                            } label: {
                                if favorite.category
                                    == "recipe" {
                                    Label(
                                        favorite.title,
                                        systemImage:
                                            "wand.and.stars"
                                    )
                                } else {
                                    Text(
                                        favorite.title
                                    )
                                }
                            }
                            .buttonStyle(
                                .bordered
                            )
                            .controlSize(
                                .small
                            )
                            .help(
                                favorite.prompt
                            )
                        }
                    }
                }
            }

            if let error =
                controller.errorMessage,
               controller
                .favorites.isEmpty {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            }
        }
        .task {
            await controller
                .loadIfNeeded()
        }
        .sheet(
            isPresented:
                $showingManager
        ) {
            PromptFavoritesManagerView()
                .environmentObject(
                    controller
                )
        }
    }
}


private struct PromptFavoritesManagerView:
    View
{
    @EnvironmentObject
    private var controller:
        PromptFavoritesController

    @Environment(\.dismiss)
    private var dismiss

    @State
    private var showingEditor = false

    @State
    private var editingID: String?

    @State
    private var draftTitle = ""

    @State
    private var draftPrompt = ""

    @State
    private var pendingDelete:
        PromptFavorite?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(
                    alignment: .leading,
                    spacing: 3
                ) {
                    Text(
                        "Favorite Prompts"
                    )
                    .font(.title2)
                    .fontWeight(
                        .semibold
                    )

                    Text(
                        "Favorites fill the prompt box so you can review or edit them before sending."
                    )
                    .font(.caption)
                    .foregroundStyle(
                        .secondary
                    )
                }

                Spacer()

                Button {
                    beginAdd()
                } label: {
                    Label(
                        "Add Favorite",
                        systemImage:
                            "plus"
                    )
                }

                Button("Done") {
                    dismiss()
                }
                .keyboardShortcut(
                    .cancelAction
                )
            }
            .padding(20)

            Divider()

            List {
                Section("Built-in") {
                    ForEach(
                        controller.builtIns
                    ) { favorite in
                        favoriteReadOnlyRow(
                            favorite
                        )
                    }
                }

                Section("My Favorites") {
                    if controller
                        .customFavorites
                        .isEmpty {
                        Text(
                            "No custom favorites yet."
                        )
                        .foregroundStyle(
                            .secondary
                        )
                    }

                    ForEach(
                        controller
                            .customFavorites
                    ) { favorite in
                        customFavoriteRow(
                            favorite
                        )
                    }
                }
            }

            if let error =
                controller.errorMessage {
                Divider()

                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(
                        .enabled
                    )
                    .padding(12)
            }
        }
        .frame(
            minWidth: 640,
            minHeight: 500
        )
        .task {
            await controller
                .loadIfNeeded()
        }
        .sheet(
            isPresented:
                $showingEditor
        ) {
            favoriteEditor
        }
        .confirmationDialog(
            "Delete this favorite?",
            isPresented:
                Binding(
                    get: {
                        pendingDelete
                            != nil
                    },
                    set: {
                        if !$0 {
                            pendingDelete =
                                nil
                        }
                    }
                ),
            titleVisibility:
                .visible
        ) {
            Button(
                "Delete Favorite",
                role: .destructive
            ) {
                guard let favorite =
                    pendingDelete
                else {
                    return
                }

                pendingDelete = nil

                Task {
                    _ = await controller
                        .deleteCustom(
                            id: favorite.id
                        )
                }
            }

            Button(
                "Cancel",
                role: .cancel
            ) {
                pendingDelete = nil
            }
        }
    }

    private func favoriteReadOnlyRow(
        _ favorite:
            PromptFavorite
    ) -> some View {
        VStack(
            alignment: .leading,
            spacing: 4
        ) {
            HStack {
                Text(favorite.title)
                    .fontWeight(.medium)

                Spacer()

                Text(
                    favorite.category == "recipe"
                        ? "Built-in Recipe"
                        : "Built-in"
                )
                .font(.caption2)
                .foregroundStyle(
                    .secondary
                )
            }

            Text(favorite.prompt)
                .font(.caption)
                .foregroundStyle(
                    .secondary
                )
                .lineLimit(3)
        }
        .padding(.vertical, 4)
    }

    private func customFavoriteRow(
        _ favorite:
            PromptFavorite
    ) -> some View {
        HStack(
            alignment: .top,
            spacing: 12
        ) {
            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text(favorite.title)
                    .fontWeight(.medium)

                Text(favorite.prompt)
                    .font(.caption)
                    .foregroundStyle(
                        .secondary
                    )
                    .lineLimit(3)
            }

            Spacer()

            Button {
                beginEdit(
                    favorite
                )
            } label: {
                Image(
                    systemName:
                        "pencil"
                )
            }
            .buttonStyle(.borderless)
            .help("Edit favorite")

            Button(
                role: .destructive
            ) {
                pendingDelete =
                    favorite
            } label: {
                Image(
                    systemName:
                        "trash"
                )
            }
            .buttonStyle(.borderless)
            .help("Delete favorite")
        }
        .padding(.vertical, 4)
    }

    private var favoriteEditor:
        some View
    {
        VStack(
            alignment: .leading,
            spacing: 16
        ) {
            Text(
                editingID == nil
                    ? "Add Favorite"
                    : "Edit Favorite"
            )
            .font(.title2)
            .fontWeight(.semibold)

            TextField(
                "Button title",
                text: $draftTitle
            )
            .textFieldStyle(
                .roundedBorder
            )

            Text("Prompt")
                .font(.headline)

            TextEditor(
                text: $draftPrompt
            )
            .font(.body)
            .frame(
                minHeight: 160
            )
            .padding(6)
            .background(
                RoundedRectangle(
                    cornerRadius: 8
                )
                .fill(.quaternary)
            )

            HStack {
                Spacer()

                Button("Cancel") {
                    showingEditor =
                        false
                }

                Button("Save") {
                    Task {
                        let saved =
                            await controller
                                .upsertCustom(
                                    id:
                                        editingID,
                                    title:
                                        draftTitle,
                                    prompt:
                                        draftPrompt
                                )

                        if saved {
                            showingEditor =
                                false
                        }
                    }
                }
                .buttonStyle(
                    .borderedProminent
                )
                .disabled(
                    draftTitle
                        .trimmingCharacters(
                            in:
                                .whitespacesAndNewlines
                        )
                        .isEmpty
                    || draftPrompt
                        .trimmingCharacters(
                            in:
                                .whitespacesAndNewlines
                        )
                        .isEmpty
                    || controller
                        .isLoading
                )
            }
        }
        .padding(24)
        .frame(
            width: 520,
            height: 380
        )
    }

    private func beginAdd() {
        editingID = nil
        draftTitle = ""
        draftPrompt = ""
        showingEditor = true
    }

    private func beginEdit(
        _ favorite:
            PromptFavorite
    ) {
        editingID = favorite.id
        draftTitle = favorite.title
        draftPrompt = favorite.prompt
        showingEditor = true
    }
}
