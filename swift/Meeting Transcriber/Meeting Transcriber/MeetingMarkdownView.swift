import AppKit
import SwiftUI

struct MeetingMarkdownView: View {
    let markdown: String

    var body: some View {
        SelectableMarkdownTextView(
            markdown: markdown
        )
    }
}


struct MeetingMarkdownScrollView: NSViewRepresentable {
    let markdown: String
    let scrollToBottomToken: Int

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSTextView.scrollableTextView()
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .noBorder

        guard let textView = scrollView.documentView as? NSTextView else {
            return scrollView
        }

        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 0, height: 0)
        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true
        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true
        textView.autoresizingMask = [.width]

        context.coordinator.textView = textView
        context.coordinator.scrollView = scrollView

        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else {
            return
        }

        let contentChanged = context.coordinator.lastMarkdown != markdown
        if contentChanged {
            textView.textStorage?.setAttributedString(
                MarkdownRenderer.render(markdown)
            )
            context.coordinator.lastMarkdown = markdown
        }

        resizeDocumentView(textView, in: scrollView)

        let shouldScroll =
            context.coordinator.lastScrollToBottomToken
            != scrollToBottomToken

        if shouldScroll {
            context.coordinator.lastScrollToBottomToken = scrollToBottomToken
            DispatchQueue.main.async {
                self.resizeDocumentView(textView, in: scrollView)
                textView.scrollToEndOfDocument(nil)
            }
        }
    }

    private func resizeDocumentView(
        _ textView: NSTextView,
        in scrollView: NSScrollView
    ) {
        let width = max(scrollView.contentSize.width, 1)

        guard
            let textContainer = textView.textContainer,
            let layoutManager = textView.layoutManager
        else {
            return
        }

        if abs(textView.frame.width - width) > 0.5 {
            textView.frame.size.width = width
        }

        textContainer.containerSize = NSSize(
            width: width,
            height: CGFloat.greatestFiniteMagnitude
        )
        textContainer.widthTracksTextView = true

        layoutManager.ensureLayout(for: textContainer)
        let usedRect = layoutManager.usedRect(for: textContainer)
        let height = max(
            scrollView.contentSize.height,
            ceil(usedRect.maxY + (textView.textContainerInset.height * 2))
        )

        if abs(textView.frame.height - height) > 0.5 {
            textView.frame.size.height = height
        }
    }

    final class Coordinator {
        weak var textView: NSTextView?
        weak var scrollView: NSScrollView?
        var lastMarkdown: String?
        var lastScrollToBottomToken: Int?
    }
}

struct SelectableStructuredTextView: View {
    let text: String

    var body: some View {
        SelectableStructuredNSTextView(
            text: text
        )
    }
}

private struct SelectableStructuredNSTextView: NSViewRepresentable {
    let text: String

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(
        context: Context
    ) -> NSTextView {
        let textView = NSTextView()

        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = false

        textView.textContainerInset = NSSize(
            width: 0,
            height: 0
        )

        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true

        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true

        textView.setContentHuggingPriority(
            .defaultLow,
            for: .horizontal
        )

        textView.setContentCompressionResistancePriority(
            .defaultLow,
            for: .horizontal
        )

        return textView
    }

    func updateNSView(
        _ textView: NSTextView,
        context: Context
    ) {
        if context.coordinator.lastText != text {
            textView.textStorage?.setAttributedString(
                StructuredTextRenderer.render(
                    text
                )
            )
            context.coordinator.lastText = text
        }

        recalculateHeight(
            textView,
            coordinator: context.coordinator
        )
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        nsView: NSTextView,
        context: Context
    ) -> CGSize? {
        let width =
            proposal.width
            ?? nsView.bounds.width

        guard
            width.isFinite,
            width > 0,
            width < 100_000
        else {
            return nil
        }

        nsView.frame.size.width = width

        guard
            let textContainer =
                nsView.textContainer,
            let layoutManager =
                nsView.layoutManager
        else {
            return nil
        }

        textContainer.containerSize = NSSize(
            width: width,
            height: .greatestFiniteMagnitude
        )
        textContainer.widthTracksTextView = true

        layoutManager.ensureLayout(
            for: textContainer
        )

        let usedRect =
            layoutManager.usedRect(
                for: textContainer
            )

        return CGSize(
            width: width,
            height: ceil(usedRect.height)
        )
    }

    private func recalculateHeight(
        _ textView: NSTextView,
        coordinator: Coordinator
    ) {
        guard
            let textContainer =
                textView.textContainer,
            let layoutManager =
                textView.layoutManager
        else {
            return
        }

        let width = textView.bounds.width

        guard
            width.isFinite,
            width > 0,
            width < 100_000
        else {
            return
        }

        textContainer.containerSize = NSSize(
            width: width,
            height: .greatestFiniteMagnitude
        )

        layoutManager.ensureLayout(
            for: textContainer
        )

        let height = ceil(
            layoutManager
                .usedRect(
                    for: textContainer
                )
                .height
        )

        if coordinator.lastHeight != height {
            coordinator.lastHeight = height

            DispatchQueue.main.async {
                textView.invalidateIntrinsicContentSize()
            }
        }
    }

    final class Coordinator {
        var lastText: String?
        var lastHeight: CGFloat = 0
    }
}

private enum StructuredTextRenderer {
    static func render(
        _ text: String
    ) -> NSAttributedString {
        let output =
            NSMutableAttributedString()

        let normalized = text
            .replacingOccurrences(
                of: "\r\n",
                with: "\n"
            )

        let lines = normalized
            .split(
                separator: "\n",
                omittingEmptySubsequences: false
            )
            .map(String.init)

        let sectionTitles: Set<String> = [
            "CRITERIA",
            "SUPPORTING MEETINGS",
            "PRIORITIES",
            "OPEN QUESTIONS",
            "ACTIONS / FOLLOW-UPS",
        ]

        for (index, rawLine) in lines.enumerated() {
            let trimmed =
                rawLine.trimmingCharacters(
                    in: .whitespaces
                )

            let isDashOnly =
                !trimmed.isEmpty
                && trimmed.allSatisfy {
                    $0 == "-"
                }

            if isDashOnly {
                continue
            }

            let font: NSFont
            let color: NSColor
            let lineText: String

            if trimmed.hasPrefix("SESSION:") {
                font = NSFont.systemFont(
                    ofSize: 13,
                    weight: .semibold
                )
                color = .labelColor
                lineText = trimmed

            } else if sectionTitles.contains(
                trimmed
            ) {
                font = NSFont.systemFont(
                    ofSize: 12,
                    weight: .semibold
                )
                color = .labelColor
                lineText = trimmed

            } else {
                font = NSFont.systemFont(
                    ofSize:
                        NSFont.systemFontSize
                )
                color = .secondaryLabelColor
                lineText = rawLine
            }

            let paragraph =
                NSMutableParagraphStyle()
            paragraph.lineSpacing = 1.5

            if trimmed.hasPrefix("•")
                || trimmed.hasPrefix("- ") {
                paragraph.firstLineHeadIndent = 0
                paragraph.headIndent = 12
            }

            let attributed =
                NSAttributedString(
                    string: lineText,
                    attributes: [
                        .font: font,
                        .foregroundColor: color,
                        .paragraphStyle: paragraph,
                    ]
                )

            output.append(attributed)

            if index < lines.count - 1 {
                output.append(
                    NSAttributedString(
                        string: "\n"
                    )
                )
            }
        }

        return output
    }
}

private struct SelectableMarkdownTextView: NSViewRepresentable {
    let markdown: String

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(
        context: Context
    ) -> NSTextView {
        let textView = NSTextView()

        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = false

        textView.textContainerInset = NSSize(
            width: 0,
            height: 0
        )

        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true

        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true

        textView.setContentHuggingPriority(
            .defaultLow,
            for: .horizontal
        )

        textView.setContentCompressionResistancePriority(
            .defaultLow,
            for: .horizontal
        )

        return textView
    }

    func updateNSView(
        _ textView: NSTextView,
        context: Context
    ) {
        let attributed =
            MarkdownRenderer.render(
                markdown
            )

        if context.coordinator.lastMarkdown
            != markdown {
            textView.textStorage?.setAttributedString(
                attributed
            )
            context.coordinator.lastMarkdown =
                markdown
        }

        recalculateHeight(
            textView,
            coordinator: context.coordinator
        )
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        nsView: NSTextView,
        context: Context
    ) -> CGSize? {
        let width =
            proposal.width
            ?? nsView.bounds.width

        guard
            width.isFinite,
            width > 0,
            width < 100_000
        else {
            return nil
        }

        nsView.frame.size.width = width

        guard
            let textContainer =
                nsView.textContainer,
            let layoutManager =
                nsView.layoutManager
        else {
            return nil
        }

        textContainer.containerSize = NSSize(
            width: width,
            height: .greatestFiniteMagnitude
        )

        textContainer.widthTracksTextView = true

        layoutManager.ensureLayout(
            for: textContainer
        )

        let usedRect =
            layoutManager.usedRect(
                for: textContainer
            )

        return CGSize(
            width: width,
            height: ceil(usedRect.height)
        )
    }

    private func recalculateHeight(
        _ textView: NSTextView,
        coordinator: Coordinator
    ) {
        guard
            let textContainer =
                textView.textContainer,
            let layoutManager =
                textView.layoutManager
        else {
            return
        }

        let width = textView.bounds.width

        guard
            width.isFinite,
            width > 0,
            width < 100_000
        else {
            return
        }

        textContainer.containerSize = NSSize(
            width: width,
            height: .greatestFiniteMagnitude
        )

        layoutManager.ensureLayout(
            for: textContainer
        )

        let height = ceil(
            layoutManager
                .usedRect(
                    for: textContainer
                )
                .height
        )

        if coordinator.lastHeight != height {
            coordinator.lastHeight = height

            DispatchQueue.main.async {
                textView.invalidateIntrinsicContentSize()
            }
        }
    }

    final class Coordinator {
        var lastMarkdown: String?
        var lastHeight: CGFloat = 0
    }
}

enum MarkdownPresentationNormalizer {
    private static let sentenceCaseSections: Set<String> = [
        "open questions",
        "risks & concerns",
        "risks and concerns",
    ]

    static func normalize(_ markdown: String) -> String {
        var activeHeading: String?

        return markdown
            .replacingOccurrences(of: "\r\n", with: "\n")
            .split(separator: "\n", omittingEmptySubsequences: false)
            .map(String.init)
            .map { line in
                let trimmed = line.trimmingCharacters(in: .whitespaces)

                if trimmed.hasPrefix("#") {
                    let heading = trimmed
                        .drop(while: { $0 == "#" || $0 == " " || $0 == "\t" })
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                        .lowercased()
                    activeHeading = heading
                    return line
                }

                guard
                    let activeHeading,
                    sentenceCaseSections.contains(activeHeading),
                    trimmed.hasPrefix("- ") || trimmed.hasPrefix("* ")
                else {
                    return line
                }

                return sentenceCaseBullet(line)
            }
            .joined(separator: "\n")
    }

    private static func sentenceCaseBullet(_ line: String) -> String {
        var characters = Array(line)
        guard let index = characters.indices.first(where: { characters[$0].isLetter })
        else {
            return line
        }

        let uppercased = String(characters[index]).uppercased()
        guard uppercased.count == 1, let character = uppercased.first else {
            return line
        }
        characters[index] = character
        return String(characters)
    }
}

private enum MarkdownRenderer {
    static func render(
        _ markdown: String
    ) -> NSAttributedString {
        let output =
            NSMutableAttributedString()

        let normalizedMarkdown =
            MarkdownPresentationNormalizer.normalize(
                markdown
            )

        let blocks =
            MarkdownBlock.parse(
                normalizedMarkdown
            )

        for (index, block) in
            blocks.enumerated() {
            if index > 0 {
                output.append(
                    NSAttributedString(
                        string:
                            spacingBefore(block)
                    )
                )
            }

            let rendered =
                renderBlock(
                    block
                )

            output.append(rendered)
        }

        return output
    }

    private static func renderBlock(
        _ block: MarkdownBlock
    ) -> NSAttributedString {
        let text: String
        let font: NSFont

        switch block.kind {
        case .heading1:
            text = block.text
            font = NSFont.systemFont(
                ofSize: 16,
                weight: .semibold
            )

        case .heading2:
            text = block.text
            font = NSFont.systemFont(
                ofSize: 13,
                weight: .semibold
            )

        case .heading3:
            text = block.text
            font = NSFont.systemFont(
                ofSize: 12,
                weight: .semibold
            )

        case .bullet:
            text = "• \(block.text)"
            font = NSFont.systemFont(
                ofSize:
                    NSFont.systemFontSize
            )

        case .numbered(let number):
            text =
                "\(number). \(block.text)"
            font = NSFont.systemFont(
                ofSize:
                    NSFont.systemFontSize
            )

        case .paragraph:
            text = block.text
            font = NSFont.systemFont(
                ofSize:
                    NSFont.systemFontSize
            )
        }

        let result =
            NSMutableAttributedString(
                string: text,
                attributes: [
                    .font: font,
                    .foregroundColor:
                        NSColor.labelColor,
                ]
            )

        applyInlineMarkdown(
            to: result
        )

        return result
    }

    private static func applyInlineMarkdown(
        to string:
            NSMutableAttributedString
    ) {
        applyDelimitedStyle(
            pattern: #"\*\*(.+?)\*\*"#,
            to: string,
            bold: true
        )

        applyDelimitedStyle(
            pattern: #"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"#,
            to: string,
            italic: true
        )
    }

    private static func applyDelimitedStyle(
        pattern: String,
        to string:
            NSMutableAttributedString,
        bold: Bool = false,
        italic: Bool = false
    ) {
        guard let regex =
            try? NSRegularExpression(
                pattern: pattern
            )
        else {
            return
        }

        let wholeRange = NSRange(
            location: 0,
            length: string.length
        )

        let matches =
            regex.matches(
                in: string.string,
                range: wholeRange
            )
            .reversed()

        for match in matches {
            guard match.numberOfRanges >= 2 else {
                continue
            }

            let fullRange =
                match.range(at: 0)

            let innerRange =
                match.range(at: 1)

            guard
                fullRange.location
                    != NSNotFound,
                innerRange.location
                    != NSNotFound
            else {
                continue
            }

            let raw =
                string.attributedSubstring(
                    from: innerRange
                )

            let replacement =
                NSMutableAttributedString(
                    attributedString: raw
                )

            replacement.enumerateAttribute(
                .font,
                in: NSRange(
                    location: 0,
                    length:
                        replacement.length
                )
            ) {
                value,
                range,
                _ in

                let baseFont =
                    value as? NSFont
                    ?? NSFont.systemFont(
                        ofSize:
                            NSFont.systemFontSize
                    )

                var traits =
                    baseFont
                        .fontDescriptor
                        .symbolicTraits

                if bold {
                    traits.insert(.bold)
                }

                if italic {
                    traits.insert(.italic)
                }

                let descriptor =
                    baseFont
                        .fontDescriptor
                        .withSymbolicTraits(
                            traits
                        )

                if let updatedFont =
                    NSFont(
                        descriptor:
                            descriptor,
                        size:
                            baseFont
                                .pointSize
                    ) {
                    replacement.addAttribute(
                        .font,
                        value: updatedFont,
                        range: range
                    )
                }
            }

            string.replaceCharacters(
                in: fullRange,
                with: replacement
            )
        }
    }

    private static func spacingBefore(
        _ block: MarkdownBlock
    ) -> String {
        switch block.kind {
        case .heading1,
             .heading2,
             .heading3:
            return "\n\n"

        case .bullet,
             .numbered:
            return "\n"

        case .paragraph:
            return "\n\n"
        }
    }
}

private struct MarkdownBlock {
    enum Kind {
        case heading1
        case heading2
        case heading3
        case bullet
        case numbered(Int)
        case paragraph
    }

    let kind: Kind
    let text: String

    static func parse(
        _ markdown: String
    ) -> [MarkdownBlock] {
        let lines =
            markdown
                .replacingOccurrences(
                    of: "\r\n",
                    with: "\n"
                )
                .split(
                    separator: "\n",
                    omittingEmptySubsequences:
                        false
                )
                .map(String.init)

        var result:
            [MarkdownBlock] = []

        var paragraphLines:
            [String] = []

        func flushParagraph() {
            guard
                !paragraphLines.isEmpty
            else {
                return
            }

            let text =
                paragraphLines
                    .joined(
                        separator: " "
                    )
                    .trimmingCharacters(
                        in:
                            .whitespacesAndNewlines
                    )

            if !text.isEmpty {
                result.append(
                    MarkdownBlock(
                        kind:
                            .paragraph,
                        text: text
                    )
                )
            }

            paragraphLines.removeAll(
                keepingCapacity: true
            )
        }

        for rawLine in lines {
            let line =
                rawLine
                    .trimmingCharacters(
                        in:
                            .whitespaces
                    )

            if line.isEmpty {
                flushParagraph()
                continue
            }

            if line.hasPrefix(
                "### "
            ) {
                flushParagraph()
                result.append(
                    MarkdownBlock(
                        kind:
                            .heading3,
                        text:
                            String(
                                line
                                    .dropFirst(
                                        4
                                    )
                            )
                    )
                )
                continue
            }

            if line.hasPrefix(
                "## "
            ) {
                flushParagraph()
                result.append(
                    MarkdownBlock(
                        kind:
                            .heading2,
                        text:
                            String(
                                line
                                    .dropFirst(
                                        3
                                    )
                            )
                    )
                )
                continue
            }

            if line.hasPrefix(
                "# "
            ) {
                flushParagraph()
                result.append(
                    MarkdownBlock(
                        kind:
                            .heading1,
                        text:
                            String(
                                line
                                    .dropFirst(
                                        2
                                    )
                            )
                    )
                )
                continue
            }

            if
                line.hasPrefix("- ")
                || line.hasPrefix("* ")
            {
                flushParagraph()
                result.append(
                    MarkdownBlock(
                        kind:
                            .bullet,
                        text:
                            String(
                                line
                                    .dropFirst(
                                        2
                                    )
                            )
                    )
                )
                continue
            }

            if let numbered =
                parseNumberedItem(
                    line
                ) {
                flushParagraph()
                result.append(
                    MarkdownBlock(
                        kind:
                            .numbered(
                                numbered
                                    .number
                            ),
                        text:
                            numbered
                                .text
                    )
                )
                continue
            }

            paragraphLines.append(
                line
            )
        }

        flushParagraph()

        return result
    }

    private static func parseNumberedItem(
        _ line: String
    ) -> (
        number: Int,
        text: String
    )? {
        guard
            let dotIndex =
                line.firstIndex(
                    of: "."
                )
        else {
            return nil
        }

        let numberText =
            line[..<dotIndex]

        guard
            let number =
                Int(numberText),
            line.index(
                after: dotIndex
            ) < line.endIndex
        else {
            return nil
        }

        let afterDot =
            line.index(
                after: dotIndex
            )

        guard
            line[afterDot] == " "
        else {
            return nil
        }

        let textStart =
            line.index(
                after: afterDot
            )

        return (
            number,
            String(
                line[
                    textStart...
                ]
            )
        )
    }
}
