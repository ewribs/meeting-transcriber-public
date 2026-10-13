
# Allow direct execution after repository reorganization.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import sys
from pathlib import Path

from config import (
    ARCHIVE_DIR,
    ARCHIVED_M4A_RETENTION_DAYS,
    LLM_CONTEXT_SIZE,
    LLM_MODEL,
    M4A_RETENTION_DAYS,
    MEETINGS_DIR,
    OUTPUT_DIR,
)
from app_settings import (
    load_app_settings,
    save_app_settings,
    update_app_setting,
)
from ollama_models import (
    discover_installed_ollama_models,
)
from hardware_profile import (
    detect_hardware_profile,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QTextBrowser,
    QListWidgetItem,
    QTabWidget,
    QLineEdit,
    QComboBox,
    QInputDialog,
    QMessageBox,
    QDateEdit,
    QHBoxLayout,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFileDialog,
    QSpinBox,
    QProgressBar,
    QCheckBox,
    QProxyStyle,
    QStyle,
)

from PySide6.QtGui import (
    QPainter,
    QPen,
)

from PySide6.QtCore import (
    QThread,
    Qt,
    QDate,
    QTimer,
    QElapsedTimer,
)

from query.sessions import (
    load_chat_session,
    save_chat_session,
    rename_chat_session,
    delete_chat_session,
)

from meeting_selector import load_meeting_index
from meeting_browser import (
    build_meeting_browser_entries,
    count_unpublished,
    meeting_fields_match_filters,
)
from meeting_selection_ui import (
    MeetingSelectionRow,
    selected_runs,
    selected_count_label,
    context_status_label,
    in_context,
)
from session_browser import (
    load_session_browser_entries,
)
from session_actions import (
    CriteriaRequiredError,
    DuplicateSessionNameError,
    FixedSessionError,
    NoMatchingMeetingsError,
    SessionAlreadyCurrent,
    create_dynamic_session as create_dynamic_session_action,
    edit_dynamic_session as edit_dynamic_session_action,
    rename_session as rename_session_action,
    refresh_dynamic_session as refresh_dynamic_session_action,
    delete_session as delete_session_action,
    save_fixed_session as save_fixed_session_action,
)
from session_criteria_ui import (
    ANY_PERSON_LABEL,
    DEFAULT_HISTORY_LABEL,
    HISTORY_OPTIONS,
    available_people,
    build_create_criteria,
    build_edit_criteria,
    criteria_present,
    edit_history_state,
)
from preferences_ui import (
    CONTEXT_SIZE_OPTIONS,
    archive_status_text,
    context_size_state,
    merge_model_choices,
    model_status_text,
    preferences_saved_message,
    selected_context_size,
    validate_preferences,
)
from query.session_context import select_session_meetings
from context_service import (
    NoLoadableMeetingsError,
    NoMeetingsSelectedError,
    build_ad_hoc_context,
    build_saved_session_context,
    resume_saved_session,
)

from conversation_service import (
    append_query_exchange,
)

from gui_workers import (
    QueryWorker,
    TranscriptionWorker,
    PublishWorker,
)

from query_presentation import (
    format_auto_execution_tooltip,
    format_elapsed,
    format_query_error_status,
    format_query_finished_status,
    format_query_ready_status,
    format_query_working_status,
    format_session_prep,
    render_conversation_markdown,
)


class MeetingCheckStyle(QProxyStyle):
    """Paint QListWidget check indicators consistently on macOS."""

    def drawPrimitive(
        self,
        element,
        option,
        painter: QPainter,
        widget=None,
    ):
        if (
            element
            != QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck
        ):
            return super().drawPrimitive(
                element,
                option,
                painter,
                widget,
            )

        rect = option.rect.adjusted(1, 1, -1, -1)
        size = min(rect.width(), rect.height(), 18)
        rect.setSize(rect.size().boundedTo(
            rect.size().__class__(size, size)
        ))
        rect.moveCenter(option.rect.center())

        is_checked = bool(
            option.state & QStyle.StateFlag.State_On
        )
        is_enabled = bool(
            option.state & QStyle.StateFlag.State_Enabled
        )

        palette = option.palette
        border_color = (
            palette.mid().color()
            if is_enabled
            else palette.midlight().color()
        )
        fill_color = (
            palette.highlight().color()
            if is_checked
            else palette.base().color()
        )

        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )
        painter.setPen(QPen(border_color, 1.25))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(rect, 4, 4)

        if is_checked:
            pen = QPen(
                palette.highlightedText().color(),
                2.2,
            )
            pen.setCapStyle(
                Qt.PenCapStyle.RoundCap
            )
            pen.setJoinStyle(
                Qt.PenJoinStyle.RoundJoin
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            left = rect.left() + rect.width() * 0.24
            mid_x = rect.left() + rect.width() * 0.43
            right = rect.left() + rect.width() * 0.77
            mid_y = rect.top() + rect.height() * 0.55
            low_y = rect.top() + rect.height() * 0.72
            high_y = rect.top() + rect.height() * 0.31

            painter.drawLine(
                int(left),
                int(mid_y),
                int(mid_x),
                int(low_y),
            )
            painter.drawLine(
                int(mid_x),
                int(low_y),
                int(right),
                int(high_y),
            )

        painter.restore()
from transcription_queue import TranscriptionQueueState
from queue_orchestrator import TranscriptionQueueOrchestrator
from transcribe_ui import (
    queue_action_state,
    queue_completion_detail,
    queue_completion_message,
    queue_rows,
    source_summary,
    workflow_complete,
    workflow_idle,
    workflow_queued,
    workflow_running,
)



class MeetingTranscriberWindow(
    QMainWindow,
):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Meeting Transcriber"
        )

        self.resize(
            1200,
            800,
        )

        self._build_ui()

        self._load_sessions()
        self._load_meetings()

        self.current_session = None
        self.current_context = None

        self.current_meeting_dirs = []

        self.query_thread = None
        self.query_worker = None

        self.pending_user_prompt = None

        self.transcribe_thread = None
        self.transcribe_worker = None
        self.publish_thread = None
        self.publish_worker = None
        self.current_transcription_run_dir = None
        self.current_transcription_source = None

        self.queue_state = TranscriptionQueueState()
        self.queue_orchestrator = TranscriptionQueueOrchestrator(
            self.queue_state
        )

        self.batch_publish_mode = None
        self.batch_publish_current_run_dir = None
        self.bulk_publish_index = -1

    def _build_ui(self):
        settings_menu = self.menuBar().addMenu(
            "Settings"
        )

        preferences_action = settings_menu.addAction(
            "Preferences…"
        )

        preferences_action.triggered.connect(
            self._open_preferences
        )

        main_splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        self.left_tabs = QTabWidget()

        transcribe_panel = QWidget()
        transcribe_layout = QVBoxLayout(
            transcribe_panel
        )

        transcribe_intro = QLabel(
            "Add one or more M4A recordings. Meetings are "
            "transcribed sequentially so the Mac is not running "
            "multiple Whisper/Qwen pipelines at the same time."
        )
        transcribe_intro.setWordWrap(
            True
        )

        transcribe_layout.addWidget(
            transcribe_intro
        )

        self.transcribe_source_input = QLineEdit()
        self.transcribe_source_input.setReadOnly(
            True
        )
        self.transcribe_source_input.setPlaceholderText(
            "No recording currently processing"
        )

        transcribe_layout.addWidget(
            QLabel("Current recording")
        )
        transcribe_layout.addWidget(
            self.transcribe_source_input
        )

        self.choose_transcribe_source_button = QPushButton(
            "Add Recordings…"
        )
        self.choose_transcribe_source_button.clicked.connect(
            self._choose_transcription_source
        )

        transcribe_layout.addWidget(
            self.choose_transcribe_source_button
        )

        self.clear_transcription_queue_button = QPushButton(
            "Clear Queue"
        )
        self.clear_transcription_queue_button.clicked.connect(
            self._clear_transcription_queue
        )
        self.clear_transcription_queue_button.setEnabled(
            False
        )

        transcribe_layout.addWidget(
            self.clear_transcription_queue_button
        )

        self.remove_queue_item_button = QPushButton(
            "Remove Selected"
        )
        self.remove_queue_item_button.clicked.connect(
            self._remove_selected_queue_item
        )
        self.remove_queue_item_button.setEnabled(False)
        transcribe_layout.addWidget(
            self.remove_queue_item_button
        )

        self.clear_completed_queue_button = QPushButton(
            "Clear Completed"
        )
        self.clear_completed_queue_button.clicked.connect(
            self._clear_completed_queue_items
        )
        self.clear_completed_queue_button.setEnabled(False)
        transcribe_layout.addWidget(
            self.clear_completed_queue_button
        )

        self.retry_failed_queue_button = QPushButton(
            "Retry Failed"
        )
        self.retry_failed_queue_button.clicked.connect(
            self._retry_failed_queue_items
        )
        self.retry_failed_queue_button.setEnabled(False)
        transcribe_layout.addWidget(
            self.retry_failed_queue_button
        )

        transcribe_layout.addSpacing(
            10
        )

        working_folder_label = QLabel(
            f"Working folder:\n{OUTPUT_DIR}"
        )
        working_folder_label.setWordWrap(
            True
        )

        archive_folder_label = QLabel(
            f"Archive folder:\n{ARCHIVE_DIR}"
        )
        archive_folder_label.setWordWrap(
            True
        )

        transcribe_layout.addWidget(
            working_folder_label
        )

        transcribe_layout.addWidget(
            archive_folder_label
        )

        transcribe_layout.addStretch(
            1
        )

        self.left_tabs.addTab(
            transcribe_panel,
            "Transcribe",
        )

        session_panel = QWidget()
        session_layout = QVBoxLayout(
            session_panel
        )

        self.session_list = QListWidget()

        self.session_list.currentItemChanged.connect(
            self._session_selected
        )

        session_layout.addWidget(
            self.session_list
        )

        self.new_dynamic_session_button = QPushButton(
            "New Dynamic Session"
        )

        self.edit_session_criteria_button = QPushButton(
            "Edit Criteria"
        )

        self.edit_session_criteria_button.setEnabled(
            False
        )

        self.rename_session_button = QPushButton(
            "Rename Session"
        )

        self.refresh_session_button = QPushButton(
            "Refresh Session"
        )

        self.refresh_session_button.setEnabled(
            False
        )

        self.delete_session_button = QPushButton(
            "Delete Session"
        )

        self.new_dynamic_session_button.clicked.connect(
            self._create_dynamic_session
        )

        self.edit_session_criteria_button.clicked.connect(
            self._edit_selected_session_criteria
        )

        self.rename_session_button.clicked.connect(
            self._rename_selected_session
        )

        self.refresh_session_button.clicked.connect(
            self._refresh_selected_session
        )

        self.delete_session_button.clicked.connect(
            self._delete_selected_session
        )

        session_layout.addWidget(
            self.new_dynamic_session_button
        )

        session_layout.addWidget(
            self.edit_session_criteria_button
        )

        session_layout.addWidget(
            self.rename_session_button
        )

        session_layout.addWidget(
            self.refresh_session_button
        )

        session_layout.addWidget(
            self.delete_session_button
        )

        meetings_panel = QWidget()
        meetings_layout = QVBoxLayout(
            meetings_panel
        )

        self.meeting_search = QLineEdit()

        self.meeting_search.setPlaceholderText(
            "Search meetings..."
        )

        self.meeting_search.textChanged.connect(
            self._filter_meetings
        )

        meetings_layout.addWidget(
            self.meeting_search
        )

        self.meeting_date_filter = QComboBox()

        self.meeting_date_filter.addItems(
            [
                "All dates",
                "Last 7 days",
                "Last 30 days",
                "This month",
                "Custom range",
            ]
        )

        self.meeting_date_filter.currentTextChanged.connect(
            self._date_filter_changed
        )

        meetings_layout.addWidget(
            self.meeting_date_filter
        )

        self.meeting_status_filter = QComboBox()
        self.meeting_status_filter.addItems(
            [
                "All statuses",
                "Published",
                "Unpublished",
            ]
        )
        self.meeting_status_filter.currentTextChanged.connect(
            self._filter_meetings
        )
        meetings_layout.addWidget(
            self.meeting_status_filter
        )

        self.custom_date_widget = QWidget()

        custom_date_layout = QHBoxLayout(
            self.custom_date_widget
        )

        custom_date_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.meeting_from_date = QDateEdit()

        self.meeting_from_date.setCalendarPopup(
            True
        )

        self.meeting_from_date.setDisplayFormat(
            "MM/dd/yyyy"
        )

        self.meeting_from_date.setDate(
            QDate.currentDate().addMonths(-1)
        )

        self.meeting_to_date = QDateEdit()

        self.meeting_to_date.setCalendarPopup(
            True
        )

        self.meeting_to_date.setDisplayFormat(
            "MM/dd/yyyy"
        )

        self.meeting_to_date.setDate(
            QDate.currentDate()
        )

        custom_date_layout.addWidget(
            QLabel("From")
        )

        custom_date_layout.addWidget(
            self.meeting_from_date
        )

        custom_date_layout.addWidget(
            QLabel("To")
        )

        custom_date_layout.addWidget(
            self.meeting_to_date
        )

        meetings_layout.addWidget(
            self.custom_date_widget
        )

        self.custom_date_widget.setVisible(
            False
        )

        self.meeting_from_date.dateChanged.connect(
            self._filter_meetings
        )

        self.meeting_to_date.dateChanged.connect(
            self._filter_meetings
        )

        self.meeting_sort = QComboBox()

        self.meeting_sort.addItems(
            [
                "Newest first",
                "Oldest first",
                "Title A-Z",
            ]
        )

        self.meeting_sort.currentTextChanged.connect(
            self._sort_meetings
        )

        meetings_layout.addWidget(
            self.meeting_sort
        )

        self.meeting_list = QListWidget()

        # Keep native ItemIsUserCheckable behavior, but paint the
        # indicator ourselves because macOS can inconsistently render
        # QListWidget check indicators after style/state changes.
        # Do not pass the QListWidget/application style into QProxyStyle.
        # QProxyStyle can assume ownership of an explicit base style, while
        # the native application style is shared.  Let the proxy resolve the
        # application style implicitly to avoid a C++ lifetime/double-delete
        # crash during shutdown.
        self.meeting_check_style = MeetingCheckStyle()
        self.meeting_check_style.setParent(
            self.meeting_list
        )
        self.meeting_list.setStyle(
            self.meeting_check_style
        )

        self.meeting_list.itemChanged.connect(
            self._meeting_selection_changed
        )

        meetings_layout.addWidget(
            self.meeting_list
        )

        self.selected_meeting_label = QLabel(
            "Selected: 0"
        )

        meetings_layout.addWidget(
            self.selected_meeting_label
        )

        self.meeting_preview = QTextBrowser()

        self.meeting_preview.setMaximumHeight(
            150
        )

        self.meeting_preview.setPlaceholderText(
            "Select a meeting to preview."
        )

        meetings_layout.addWidget(
            self.meeting_preview
        )

        self.meeting_list.currentItemChanged.connect(
            self._preview_meeting
        )

        self.meeting_publish_button = QPushButton(
            "Publish && Archive"
        )
        self.meeting_publish_button.setEnabled(
            False
        )
        self.meeting_publish_button.clicked.connect(
            self._start_selected_meeting_publish
        )

        self.meeting_publish_status_label = QLabel(
            "Select an Unpublished meeting to publish."
        )
        self.meeting_publish_status_label.setWordWrap(
            True
        )

        self.meeting_publish_elapsed_timer = QElapsedTimer()
        self.meeting_publish_elapsed_update_timer = QTimer(
            self
        )
        self.meeting_publish_elapsed_update_timer.setInterval(
            1000
        )
        self.meeting_publish_elapsed_update_timer.timeout.connect(
            self._update_meeting_publish_elapsed
        )

        self.meeting_list.currentItemChanged.connect(
            self._update_meeting_publish_action
        )

        meetings_layout.addWidget(
            self.meeting_publish_button
        )
        meetings_layout.addWidget(
            self.meeting_publish_status_label
        )

        self.save_session_button = QPushButton(
            "Save as Session"
        )

        self.save_session_button.setEnabled(
            False
        )

        self.build_context_button = QPushButton(
            "Build Context"
        )

        self.clear_selection_button = QPushButton(
            "Clear Selection"
        )

        self.select_visible_button = QPushButton(
            "Select Visible"
        )

        self.clear_visible_button = QPushButton(
            "Clear Visible"
        )

        self.save_session_button.clicked.connect(
            self._save_selected_as_session
        )

        self.clear_selection_button.clicked.connect(
            self._clear_meeting_selection
        )

        self.select_visible_button.clicked.connect(
            self._select_visible_meetings
        )

        self.clear_visible_button.clicked.connect(
            self._clear_visible_meetings
        )

        meetings_layout.addWidget(
            self.build_context_button
        )

        meetings_layout.addWidget(
            self.clear_selection_button
        )

        meetings_layout.addWidget(
            self.select_visible_button
        )

        meetings_layout.addWidget(
            self.clear_visible_button
        )

        self.build_context_button.clicked.connect(
            self._build_selected_meeting_context
        )

        meetings_layout.addWidget(
            self.save_session_button
        )

        self.left_tabs.addTab(
            meetings_panel,
            "Meetings",
        )

        self.left_tabs.addTab(
            session_panel,
            "Sessions",
        )

        self.left_tabs.currentChanged.connect(
            self._left_tab_changed
        )

        self.transcribe_center_panel = QWidget()
        transcribe_center_layout = QVBoxLayout(
            self.transcribe_center_panel
        )

        transcribe_title = QLabel(
            "Transcribe"
        )
        transcribe_title_font = (
            transcribe_title.font()
        )
        transcribe_title_font.setBold(
            True
        )
        transcribe_title_font.setPointSize(
            transcribe_title_font.pointSize() + 3
        )
        transcribe_title.setFont(
            transcribe_title_font
        )

        transcribe_center_layout.addWidget(
            transcribe_title
        )

        transcribe_description = QLabel(
            "Queue one or more recordings and transcribe them "
            "sequentially. Auto-publish can optionally archive each "
            "meeting after successful transcription."
        )
        transcribe_description.setWordWrap(
            True
        )

        transcribe_center_layout.addWidget(
            transcribe_description
        )

        unpublished_reminder_row = QWidget()
        unpublished_reminder_layout = QHBoxLayout(
            unpublished_reminder_row
        )
        unpublished_reminder_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.unpublished_meeting_label = QLabel(
            "Checking for unpublished meetings..."
        )
        self.unpublished_meeting_label.setWordWrap(
            True
        )

        self.view_unpublished_meetings_button = QPushButton(
            "View in Meetings"
        )
        self.view_unpublished_meetings_button.setVisible(
            False
        )
        self.view_unpublished_meetings_button.clicked.connect(
            self._view_unpublished_meetings
        )

        unpublished_reminder_layout.addWidget(
            self.unpublished_meeting_label,
            1,
        )
        unpublished_reminder_layout.addWidget(
            self.view_unpublished_meetings_button
        )

        transcribe_center_layout.addWidget(
            unpublished_reminder_row
        )

        transcribe_center_layout.addSpacing(
            18
        )

        queue_label = QLabel(
            "Transcription Queue"
        )
        queue_label_font = queue_label.font()
        queue_label_font.setBold(True)
        queue_label.setFont(queue_label_font)
        transcribe_center_layout.addWidget(queue_label)

        self.transcription_queue_list = QListWidget()
        self.transcription_queue_list.setMinimumHeight(150)
        self.transcription_queue_list.currentRowChanged.connect(
            lambda _row: self._update_queue_action_buttons()
        )
        transcribe_center_layout.addWidget(
            self.transcription_queue_list
        )

        self.auto_publish_checkbox = QCheckBox(
            "Publish && archive automatically after successful transcription"
        )
        self.auto_publish_checkbox.setChecked(False)
        self.auto_publish_checkbox.setToolTip(
            "When enabled, each meeting is published and archived "
            "immediately after its transcription finishes successfully. "
            "When disabled, completed meetings remain Unpublished and are "
            "managed from Meetings."
        )
        transcribe_center_layout.addWidget(
            self.auto_publish_checkbox
        )

        self.transcribe_source_summary = QLabel(
            "Current source: None"
        )
        self.transcribe_source_summary.setWordWrap(
            True
        )

        transcribe_center_layout.addWidget(
            self.transcribe_source_summary
        )

        transcribe_center_layout.addSpacing(
            18
        )

        workflow_label = QLabel(
            "Workflow"
        )
        workflow_font = workflow_label.font()
        workflow_font.setBold(
            True
        )
        workflow_label.setFont(
            workflow_font
        )

        transcribe_center_layout.addWidget(
            workflow_label
        )

        self.transcribe_status_label = QLabel(
            "1. Intake — add one or more M4A recordings\n"
            "2. Transcribe — waiting for queue\n"
            "3. Review — waiting for transcription\n"
            "4. Publish & Archive — automatic when enabled; otherwise manage in Meetings"
        )
        self.transcribe_status_label.setWordWrap(
            True
        )

        transcribe_center_layout.addWidget(
            self.transcribe_status_label
        )

        self.transcribe_progress_bar = QProgressBar()
        self.transcribe_progress_bar.setRange(
            0,
            100,
        )
        self.transcribe_progress_bar.setValue(
            0
        )
        self.transcribe_progress_bar.setTextVisible(
            True
        )

        transcribe_center_layout.addWidget(
            self.transcribe_progress_bar
        )

        self.transcribe_progress_detail = QLabel(
            "Ready for intake."
        )
        self.transcribe_progress_detail.setWordWrap(
            True
        )

        self.transcribe_elapsed_label = QLabel(
            "Elapsed: 00:00"
        )
        self.transcribe_elapsed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )

        transcribe_progress_row = QHBoxLayout()
        transcribe_progress_row.addWidget(
            self.transcribe_progress_detail,
            1,
        )
        transcribe_progress_row.addWidget(
            self.transcribe_elapsed_label
        )

        transcribe_center_layout.addLayout(
            transcribe_progress_row
        )

        self.transcribe_elapsed_timer = QElapsedTimer()
        self.transcribe_elapsed_update_timer = QTimer(
            self
        )
        self.transcribe_elapsed_update_timer.setInterval(
            1000
        )
        self.transcribe_elapsed_update_timer.timeout.connect(
            self._update_transcribe_elapsed
        )

        transcribe_center_layout.addSpacing(
            18
        )

        self.transcribe_run_button = QPushButton(
            "Start Queue"
        )
        self.transcribe_run_button.setEnabled(
            False
        )
        self.transcribe_run_button.clicked.connect(
            self._start_transcription
        )

        self.transcribe_publish_button = QPushButton(
            "Publish && Archive"
        )
        self.transcribe_publish_button.setEnabled(
            False
        )
        self.transcribe_publish_button.clicked.connect(
            self._start_publish
        )

        transcribe_center_layout.addWidget(
            self.transcribe_run_button
        )

        # Manual publishing belongs in the Meetings workspace.
        # Keep the legacy button object for existing internal callbacks,
        # but do not expose it in Transcribe.
        self.transcribe_publish_button.setVisible(False)

        transcribe_center_layout.addStretch(
            1
        )

        center_panel = QWidget()
        center_layout = QVBoxLayout(
            center_panel
        )

        right_splitter = QSplitter(
            Qt.Orientation.Vertical
        )

        context_panel = QWidget()
        context_layout = QVBoxLayout(
            context_panel
        )

        self.context_label = QLabel(
            "Session Context"
        )

        context_layout.addWidget(
            self.context_label
        )

        self.context_view = (
            QTextBrowser()
        )

        context_font = (
            self.context_view.font()
        )

        context_font.setPointSize(
            11
        )

        self.context_view.setFont(
            context_font
        )

        context_layout.addWidget(
            self.context_view
        )

        chat_panel = QWidget()
        chat_layout = QVBoxLayout(
            chat_panel
        )

        chat_header_layout = QHBoxLayout()

        chat_header_layout.addWidget(
            QLabel("Conversation")
        )

        chat_header_layout.addStretch()

        chat_header_layout.addWidget(
            QLabel("Execution")
        )

        self.execution_profile_combo = QComboBox()
        self.execution_profile_combo.addItems(
            [
                "Conservative",
                "Balanced",
                "Aggressive",
            ]
        )

        app_settings = load_app_settings()
        saved_execution_profile = (
            app_settings.get(
                "execution_profile",
                "Balanced",
            )
        )

        if (
            self.execution_profile_combo.findText(
                saved_execution_profile
            )
            < 0
        ):
            saved_execution_profile = "Balanced"

        self.execution_profile_combo.setCurrentText(
            saved_execution_profile
        )
        self.execution_profile_combo.setToolTip(
            "Controls how large a prompt Auto will send "
            "directly before switching to chunked execution."
        )
        self.execution_profile_combo.currentTextChanged.connect(
            self._execution_profile_changed
        )

        chat_header_layout.addWidget(
            self.execution_profile_combo
        )

        hardware_profile = (
            detect_hardware_profile()
        )

        self.hardware_status_label = QLabel(
            f"HW · {hardware_profile.display_label}"
        )
        self.hardware_status_label.setToolTip(
            (
                f"{hardware_profile.performance_class}\n"
                f"Auto hardware budget factor: "
                f"{hardware_profile.budget_factor:.2f}\n"
                "This is a conservative benchmark-informed "
                "heuristic, not a live performance benchmark."
            )
        )

        chat_header_layout.addWidget(
            self.hardware_status_label
        )

        self.query_status_label = QLabel(
            f"Qwen · {saved_execution_profile} · Ready"
        )
        self.query_status_label.setToolTip(
            "Run a query to see Auto execution details."
        )

        chat_header_layout.addWidget(
            self.query_status_label
        )

        self.query_elapsed_label = QLabel(
            "Elapsed: 00:00"
        )

        chat_header_layout.addWidget(
            self.query_elapsed_label
        )

        self.query_elapsed_timer = QElapsedTimer()
        self.query_elapsed_update_timer = QTimer(
            self
        )
        self.query_elapsed_update_timer.setInterval(
            1000
        )
        self.query_elapsed_update_timer.timeout.connect(
            self._update_query_elapsed
        )

        chat_layout.addLayout(
            chat_header_layout
        )

        self.chat_view = (
            QTextBrowser()
        )

        chat_layout.addWidget(
            self.chat_view
        )

        self.chat_input = (
            QPlainTextEdit()
        )

        self.chat_input.setPlaceholderText(
            "Ask about the selected "
            "meeting context..."
        )

        self.chat_input.setMaximumHeight(
            75
        )

        chat_layout.addWidget(
            self.chat_input
        )

        right_splitter.addWidget(
            context_panel
        )

        right_splitter.addWidget(
            chat_panel
        )

        right_splitter.setSizes(
            [
                430,
                370,
            ]
        )

        center_layout.addWidget(
            right_splitter
        )

        self.send_button = QPushButton(
            "Send"
        )

        self.send_button.clicked.connect(
            self._send_query
        )

        center_layout.addWidget(
            self.send_button
        )

        main_splitter.addWidget(
            self.left_tabs
        )

        main_splitter.addWidget(
            self.transcribe_center_panel
        )

        main_splitter.addWidget(
            center_panel
        )

        main_splitter.setStretchFactor(
            0,
            0,
        )

        main_splitter.setStretchFactor(
            1,
            1,
        )

        main_splitter.setStretchFactor(
            2,
            1,
        )

        main_splitter.setSizes(
            [
                260,
                940,
                940,
            ]
        )

        center_panel.setVisible(
            False
        )

        self.knowledge_center_panel = (
            center_panel
        )

        self.setCentralWidget(
            main_splitter
        )

    def _choose_transcription_source(self):
        if self.queue_state.active:
            return

        start_dir = (
            MEETINGS_DIR
            if MEETINGS_DIR.exists()
            else Path.home()
        )

        selected_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add M4A Recordings",
            str(start_dir),
            "M4A Audio (*.m4a);;All Files (*)",
        )

        if not selected_paths:
            return

        # A completed batch is historical UI state. Starting another
        # intake batch should not inherit terminal state from the prior batch.
        self.queue_state.clear_completed_batch_if_terminal()

        added = self.queue_state.add_sources(
            [Path(selected_path) for selected_path in selected_paths]
        )

        if not added:
            return

        self.current_transcription_source = (
            self.queue_state.entries[0]["source_path"]
        )
        self.current_transcription_run_dir = None

        self.transcribe_progress_bar.setValue(0)
        self.transcribe_elapsed_update_timer.stop()
        self.transcribe_elapsed_timer.invalidate()
        self.transcribe_elapsed_label.setText(
            "Elapsed: 00:00"
        )
        self.transcribe_progress_detail.setText(
            f"{len(self.queue_state.entries)} recording(s) queued."
        )
        self.transcribe_run_button.setText(
            "Start Queue"
        )
        self.transcribe_run_button.setEnabled(True)
        self.transcribe_publish_button.setText(
            "Publish && Archive"
        )
        self.transcribe_publish_button.setEnabled(False)
        self.clear_transcription_queue_button.setEnabled(True)
        self.auto_publish_checkbox.setEnabled(True)

        self.transcribe_status_label.setText(
            workflow_queued()
        )

        self._refresh_transcription_queue_list()
        self._update_transcription_source_summary(
            self.current_transcription_source
        )

    def _remove_selected_queue_item(self):
        if self.queue_state.active:
            return

        row = self.transcription_queue_list.currentRow()
        if not self.queue_state.remove(row):
            return
        self._refresh_transcription_queue_list()

        if not self.queue_state.entries:
            self._clear_transcription_queue()
            return

        self.current_transcription_source = self.queue_state.entries[0][
            "source_path"
        ]
        self.current_transcription_run_dir = None
        self._update_transcription_source_summary(
            self.current_transcription_source
        )
        self.transcribe_run_button.setEnabled(
            any(
                entry["status"] == "Waiting"
                for entry in self.queue_state.entries
            )
        )
        self._update_queue_action_buttons()

    def _clear_completed_queue_items(self):
        if self.queue_state.active:
            return

        self.queue_state.clear_completed()
        self._refresh_transcription_queue_list()

        if not self.queue_state.entries:
            self._clear_transcription_queue()
            return

        self.current_transcription_source = self.queue_state.entries[0][
            "source_path"
        ]
        self.current_transcription_run_dir = None
        self._update_transcription_source_summary(
            self.current_transcription_source
        )
        self.transcribe_run_button.setEnabled(
            any(
                entry["status"] == "Waiting"
                for entry in self.queue_state.entries
            )
        )
        self._update_queue_action_buttons()

    def _retry_failed_queue_items(self):
        if self.queue_state.active:
            return

        reset_transcription, reset_publish = (
            self.queue_state.retry_failures()
        )

        if not (reset_transcription or reset_publish):
            return
        self._refresh_transcription_queue_list()
        self.transcribe_run_button.setEnabled(
            reset_transcription > 0
        )

        if reset_publish:
            self.transcribe_progress_detail.setText(
                f"Reset {reset_transcription} transcription failure(s) "
                f"and {reset_publish} publish failure(s). "
                "Use Start Queue for transcription retries; completed "
                "local meetings can be published without retranscribing."
            )
        else:
            self.transcribe_progress_detail.setText(
                f"Reset {reset_transcription} failed transcription(s) "
                "to Waiting. Start Queue to retry only those items."
            )

        self._update_queue_action_buttons()

    def _update_queue_action_buttons(self):
        active = self.queue_state.active or (
            self.publish_thread is not None
            and self.publish_thread.isRunning()
        )
        state = queue_action_state(
            self.queue_state.entries,
            self.transcription_queue_list.currentRow(),
            active=active,
        )

        self.remove_queue_item_button.setEnabled(
            state.remove_selected
        )
        self.clear_completed_queue_button.setEnabled(
            state.clear_completed
        )
        self.retry_failed_queue_button.setEnabled(
            state.retry_failed
        )

    def _clear_transcription_queue(self):
        if self.queue_state.active:
            return

        self.queue_state.clear()
        self.current_transcription_source = None
        self.current_transcription_run_dir = None

        self.transcription_queue_list.clear()
        self.transcribe_source_input.clear()
        self.transcribe_source_summary.setText(
            "Current source: None"
        )
        self.transcribe_progress_bar.setValue(0)
        self.transcribe_elapsed_update_timer.stop()
        self.transcribe_elapsed_timer.invalidate()
        self.transcribe_elapsed_label.setText(
            "Elapsed: 00:00"
        )
        self.transcribe_progress_detail.setText(
            "Ready for intake."
        )
        self.transcribe_run_button.setText(
            "Start Queue"
        )
        self.transcribe_run_button.setEnabled(False)
        self.transcribe_publish_button.setText(
            "Publish && Archive"
        )
        self.transcribe_publish_button.setEnabled(False)
        self.clear_transcription_queue_button.setEnabled(False)
        self.auto_publish_checkbox.setEnabled(True)
        self.transcribe_status_label.setText(
            workflow_idle()
        )
        self._update_queue_action_buttons()

    def _refresh_transcription_queue_list(self):
        self.transcription_queue_list.clear()

        for label, error in queue_rows(self.queue_state.entries):
            item = QListWidgetItem(label)
            if error:
                item.setToolTip(error)
            self.transcription_queue_list.addItem(item)

        self._update_queue_action_buttons()

    def _update_transcription_source_summary(
        self,
        source_path: Path | None,
    ):
        input_text, summary = source_summary(
            source_path,
            output_dir=OUTPUT_DIR,
            archive_dir=ARCHIVE_DIR,
        )
        self.transcribe_source_input.setText(input_text)
        self.transcribe_source_summary.setText(summary)

    def _start_transcription(self):
        if self.queue_state.active:
            return

        waiting = [
            entry
            for entry in self.queue_state.entries
            if entry["status"] == "Waiting"
        ]

        if not waiting:
            QMessageBox.warning(
                self,
                "Nothing Queued",
                "Add one or more M4A recordings first.",
            )
            return

        missing = [
            entry["source_path"]
            for entry in waiting
            if not entry["source_path"].exists()
        ]
        if missing:
            QMessageBox.warning(
                self,
                "Recording Not Found",
                "One or more queued recordings no longer exist:\n\n"
                + "\n".join(str(path) for path in missing),
            )
            return

        self.queue_state.begin_run()
        self._update_queue_action_buttons()
        self.current_transcription_run_dir = None

        self.choose_transcribe_source_button.setEnabled(False)
        self.clear_transcription_queue_button.setEnabled(False)
        self.auto_publish_checkbox.setEnabled(False)
        self.transcribe_run_button.setEnabled(False)
        self.transcribe_run_button.setText(
            "Queue Running…"
        )
        self.transcribe_publish_button.setEnabled(False)
        self.transcribe_publish_button.setText(
            "Publish && Archive"
        )

        self.transcribe_progress_bar.setValue(0)
        self.transcribe_progress_detail.setText(
            "Starting transcription queue..."
        )
        self.transcribe_status_label.setText(
            workflow_running(
                auto_publish=self.auto_publish_checkbox.isChecked()
            )
        )

        self.transcribe_elapsed_timer.start()
        self.transcribe_elapsed_label.setText(
            "Elapsed: 00:00"
        )
        self.transcribe_elapsed_update_timer.start()

        self._start_next_queued_transcription()

    def _start_next_queued_transcription(self):
        action = self.queue_orchestrator.start_next_transcription()

        if action.kind == "finish":
            self._finish_transcription_queue()
            return

        next_index = action.index
        if next_index is None:
            return

        entry = self.queue_state.entries[next_index]
        source_path = entry["source_path"]

        self.current_transcription_source = source_path
        self.current_transcription_run_dir = None
        self._update_transcription_source_summary(source_path)
        self._refresh_transcription_queue_list()

        self.transcribe_progress_bar.setValue(0)
        self.transcribe_progress_detail.setText(
            f"Starting {source_path.name} "
            f"({next_index + 1}/{len(self.queue_state.entries)})..."
        )

        self.transcribe_thread = QThread()
        self.transcribe_worker = TranscriptionWorker(
            source_path
        )
        self.transcribe_worker.moveToThread(
            self.transcribe_thread
        )
        self.transcribe_thread.started.connect(
            self.transcribe_worker.run
        )
        self.transcribe_worker.progress.connect(
            self._transcription_progress
        )
        self.transcribe_worker.finished.connect(
            self._transcription_finished
        )
        self.transcribe_worker.failed.connect(
            self._transcription_failed
        )
        self.transcribe_worker.finished.connect(
            self.transcribe_thread.quit
        )
        self.transcribe_worker.failed.connect(
            self.transcribe_thread.quit
        )
        self.transcribe_thread.finished.connect(
            self.transcribe_worker.deleteLater
        )
        self.transcribe_thread.finished.connect(
            self.transcribe_thread.deleteLater
        )
        self.transcribe_thread.finished.connect(
            self._transcription_thread_finished
        )
        self.transcribe_thread.start()

    def _transcription_progress(
        self,
        message: str,
        percent: int,
    ):
        self.transcribe_progress_bar.setValue(
            percent
        )
        self.transcribe_progress_detail.setText(
            message
        )

    def _transcription_finished(
        self,
        run_dir_text: str,
    ):
        run_dir = Path(run_dir_text)
        self.current_transcription_run_dir = run_dir

        self.queue_state.mark_transcription_success(run_dir)

        self.transcribe_progress_bar.setValue(100)
        self.transcribe_progress_detail.setText(
            f"Transcription complete: {run_dir.name}"
        )
        self._refresh_transcription_queue_list()

        # Completed local runs are immediately discoverable as
        # Unpublished meetings.
        self._load_meetings()
        self._sort_meetings(
            self.meeting_sort.currentText()
        )

    def _transcription_failed(
        self,
        error: str,
    ):
        self.queue_state.mark_transcription_failure(error)

        self.transcribe_progress_detail.setText(
            f"Transcription failed: {error}"
        )
        self._refresh_transcription_queue_list()

    def _finish_transcription_queue(self):
        self.queue_state.active = False
        self.batch_publish_mode = None
        self._stop_transcribe_elapsed()

        total = self.queue_state.attempted
        successes = self.queue_state.successes
        failures = self.queue_state.failures
        published = self.queue_state.publish_successes
        publish_failures = self.queue_state.publish_failures

        self.choose_transcribe_source_button.setEnabled(True)
        self.clear_transcription_queue_button.setEnabled(True)
        self.auto_publish_checkbox.setEnabled(True)
        self.transcribe_run_button.setText("Start Queue")
        self.transcribe_run_button.setEnabled(
            any(
                entry["status"] == "Waiting"
                for entry in self.queue_state.entries
            )
        )

        ready_entries = [
            entry
            for entry in self.queue_state.entries
            if entry["status"] in {
                "Ready to Publish",
                "Publish Failed",
            }
        ]
        if len(ready_entries) == 1 and total == 1:
            self.current_transcription_run_dir = ready_entries[0]["run_dir"]
            self.transcribe_publish_button.setText("Publish && Archive")
            self.transcribe_publish_button.setEnabled(True)
        else:
            self.current_transcription_run_dir = None
            self.transcribe_publish_button.setText("Publish && Archive")
            self.transcribe_publish_button.setEnabled(False)

        auto_publish = self.auto_publish_checkbox.isChecked()
        self.transcribe_status_label.setText(
            workflow_complete(
                auto_publish=auto_publish,
                transcription_failures=failures,
                publish_failures=publish_failures,
            )
        )

        self.transcribe_progress_detail.setText(
            queue_completion_detail(
                auto_publish=auto_publish,
                successes=successes,
                transcription_failures=failures,
                published=published,
                publish_failures=publish_failures,
            )
        )

        self._load_meetings()
        self._sort_meetings(self.meeting_sort.currentText())

        message = queue_completion_message(
            auto_publish=auto_publish,
            total=total,
            successes=successes,
            transcription_failures=failures,
            published=published,
            publish_failures=publish_failures,
        )

        QMessageBox.information(
            self,
            "Transcription Queue Complete",
            message,
        )

    def _update_transcribe_elapsed(self):
        if not self.transcribe_elapsed_timer.isValid():
            return

        elapsed_ms = (
            self.transcribe_elapsed_timer.elapsed()
        )

        self.transcribe_elapsed_label.setText(
            f"Elapsed: {format_elapsed(elapsed_ms)}"
        )

    def _stop_transcribe_elapsed(self):
        self.transcribe_elapsed_update_timer.stop()

        if not self.transcribe_elapsed_timer.isValid():
            return

        elapsed_ms = (
            self.transcribe_elapsed_timer.elapsed()
        )

        self.transcribe_elapsed_label.setText(
            f"Elapsed: {format_elapsed(elapsed_ms)}"
        )

        self.transcribe_elapsed_timer.invalidate()

    def _transcription_thread_finished(self):
        self.transcribe_worker = None
        self.transcribe_thread = None

        action = self.queue_orchestrator.after_transcription(
            auto_publish=self.auto_publish_checkbox.isChecked(),
        )

        if action.kind == "idle":
            return

        if action.kind == "publish" and action.run_dir is not None:
            self._refresh_transcription_queue_list()
            self.batch_publish_mode = "auto"
            self._launch_batch_publish_worker(action.run_dir)
            return

        QTimer.singleShot(
            0,
            self._start_next_queued_transcription,
        )

    def _launch_batch_publish_worker(
        self,
        run_dir: Path,
    ):
        self.batch_publish_current_run_dir = Path(run_dir)
        self.transcribe_progress_bar.setValue(0)
        self.transcribe_progress_detail.setText(
            f"Publishing {run_dir.name}..."
        )

        self.publish_thread = QThread()
        self.publish_worker = PublishWorker(run_dir)
        self.publish_worker.moveToThread(self.publish_thread)
        self.publish_thread.started.connect(
            self.publish_worker.run
        )
        self.publish_worker.progress.connect(
            self._batch_publish_progress
        )
        self.publish_worker.finished.connect(
            self._batch_publish_finished
        )
        self.publish_worker.failed.connect(
            self._batch_publish_failed
        )
        self.publish_worker.finished.connect(
            self.publish_thread.quit
        )
        self.publish_worker.failed.connect(
            self.publish_thread.quit
        )
        self.publish_thread.finished.connect(
            self.publish_worker.deleteLater
        )
        self.publish_thread.finished.connect(
            self.publish_thread.deleteLater
        )
        self.publish_thread.finished.connect(
            self._batch_publish_thread_finished
        )
        self.publish_thread.start()

    def _batch_publish_progress(
        self,
        message: str,
        percent: int,
    ):
        self.transcribe_progress_bar.setValue(percent)
        self.transcribe_progress_detail.setText(message)

    def _find_queue_entry_for_run(
        self,
        run_dir: Path,
    ):
        return self.queue_state.find_by_run(run_dir)

    def _batch_publish_finished(
        self,
        archived_path_text: str,
        result: dict,
    ):
        run_dir = self.batch_publish_current_run_dir
        if run_dir is not None:
            self.queue_state.mark_publish_success(run_dir)
        self.transcribe_progress_bar.setValue(100)
        self.transcribe_progress_detail.setText(
            f"Published successfully: {Path(archived_path_text).name}"
        )
        self._refresh_transcription_queue_list()
        self._load_meetings()
        self._sort_meetings(self.meeting_sort.currentText())

    def _batch_publish_failed(
        self,
        error: str,
    ):
        run_dir = self.batch_publish_current_run_dir
        if run_dir is not None:
            self.queue_state.mark_publish_failure(
                run_dir,
                error,
            )
        self.transcribe_progress_detail.setText(
            f"Publish failed: {error}"
        )
        self._refresh_transcription_queue_list()
        self._load_meetings()
        self._sort_meetings(self.meeting_sort.currentText())

    def _batch_publish_thread_finished(self):
        self.publish_worker = None
        self.publish_thread = None
        mode = self.batch_publish_mode
        self.batch_publish_current_run_dir = None

        action = self.queue_orchestrator.after_publish(
            mode=mode,
        )

        if action.kind == "continue":
            QTimer.singleShot(
                0,
                self._start_next_queued_transcription,
            )
            return

        if action.kind == "continue_bulk":
            QTimer.singleShot(
                0,
                self._start_next_bulk_unpublished_publish,
            )

    def _start_bulk_unpublished_publish(self):
        if (
            self.queue_state.active
            or (
                self.publish_thread is not None
                and self.publish_thread.isRunning()
            )
        ):
            return

        unpublished = [
            meeting
            for meeting in load_meeting_index()
            if meeting.get("publish_status") == "Unpublished"
        ]

        if not unpublished:
            QMessageBox.information(
                self,
                "No Unpublished Meetings",
                "There are no completed local meetings waiting to be published.",
            )
            return

        response = QMessageBox.question(
            self,
            "Publish Unpublished Meetings",
            (
                f"Publish and archive all {len(unpublished)} "
                "unpublished meeting(s)?\n\n"
                "Each meeting will be processed sequentially. "
                "A failure will not stop the remaining meetings."
            ),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            ),
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return

        self.queue_state.entries = []
        for meeting in unpublished:
            run_dir = Path(meeting["location"])
            self.queue_state.entries.append({
                "source_path": Path(meeting.get("meeting_run", run_dir.name)),
                "status": "Waiting to Publish",
                "run_dir": run_dir,
                "error": None,
            })

        self.queue_state.publish_successes = 0
        self.queue_state.publish_failures = 0
        self.bulk_publish_index = -1
        self.batch_publish_mode = "bulk"
        self.queue_state.active = False

        self.choose_transcribe_source_button.setEnabled(False)
        self.clear_transcription_queue_button.setEnabled(False)
        self.auto_publish_checkbox.setEnabled(False)
        self.transcribe_run_button.setEnabled(False)
        self.transcribe_publish_button.setEnabled(False)

        self.transcribe_elapsed_timer.start()
        self.transcribe_elapsed_label.setText("Elapsed: 00:00")
        self.transcribe_elapsed_update_timer.start()
        self.transcribe_status_label.setText(
            "1. Intake — existing unpublished meetings loaded ✓\n"
            "2. Transcribe — already complete ✓\n"
            "3. Review — generated artifacts ready ✓\n"
            "4. Publish & Archive — bulk publishing…"
        )
        self._refresh_transcription_queue_list()
        self._start_next_bulk_unpublished_publish()

    def _start_next_bulk_unpublished_publish(self):
        next_index = None
        for index in range(
            self.bulk_publish_index + 1,
            len(self.queue_state.entries),
        ):
            if self.queue_state.entries[index]["status"] == "Waiting to Publish":
                next_index = index
                break

        if next_index is None:
            self._finish_bulk_unpublished_publish()
            return

        self.bulk_publish_index = next_index
        entry = self.queue_state.entries[next_index]
        entry["status"] = "Publishing"
        run_dir = Path(entry["run_dir"])
        self.current_transcription_run_dir = run_dir
        self._refresh_transcription_queue_list()
        self.transcribe_progress_detail.setText(
            f"Publishing {run_dir.name} "
            f"({next_index + 1}/{len(self.queue_state.entries)})..."
        )
        self._launch_batch_publish_worker(run_dir)

    def _finish_bulk_unpublished_publish(self):
        self._stop_transcribe_elapsed()
        successes = self.queue_state.publish_successes
        failures = self.queue_state.publish_failures
        total = len(self.queue_state.entries)
        self.batch_publish_mode = None

        self.choose_transcribe_source_button.setEnabled(True)
        self.clear_transcription_queue_button.setEnabled(True)
        self.auto_publish_checkbox.setEnabled(True)
        self.transcribe_run_button.setText("Start Queue")
        self.transcribe_run_button.setEnabled(False)
        self.transcribe_publish_button.setText("Publish && Archive")
        self.transcribe_publish_button.setEnabled(False)

        self.transcribe_progress_detail.setText(
            f"Bulk publish complete: {successes} published, "
            f"{failures} failed."
        )
        self.transcribe_status_label.setText(
            "1. Intake — bulk publish complete ✓\n"
            "2. Transcribe — already complete ✓\n"
            "3. Review — complete ✓\n"
            "4. Publish & Archive — complete"
        )
        self._load_meetings()
        self._sort_meetings(self.meeting_sort.currentText())

        QMessageBox.information(
            self,
            "Bulk Publish Complete",
            (
                f"Processed {total} unpublished meeting(s).\n\n"
                f"Published: {successes}\n"
                f"Failed: {failures}"
            ),
        )

    def _start_publish(self):
        run_dir = self.current_transcription_run_dir

        if run_dir is None:
            QMessageBox.warning(
                self,
                "Nothing to Publish",
                (
                    "Transcribe a meeting successfully before "
                    "publishing it from this workspace."
                ),
            )
            return

        run_dir = Path(run_dir)

        if not run_dir.exists():
            QMessageBox.warning(
                self,
                "Local Meeting Not Found",
                (
                    "The completed local meeting folder no longer "
                    "exists:\n\n"
                    f"{run_dir}"
                ),
            )
            return

        if not ARCHIVE_DIR.exists():
            QMessageBox.warning(
                self,
                "Archive Unavailable",
                (
                    "The configured archive/NAS is not available:\n\n"
                    f"{ARCHIVE_DIR}"
                ),
            )
            return

        if (ARCHIVE_DIR / run_dir.name).exists():
            QMessageBox.warning(
                self,
                "Already Published",
                (
                    "An archive folder already exists for this "
                    "meeting:\n\n"
                    f"{ARCHIVE_DIR / run_dir.name}"
                ),
            )
            return

        if (
            self.publish_thread is not None
            and self.publish_thread.isRunning()
        ):
            return

        response = QMessageBox.question(
            self,
            "Publish & Archive Meeting",
            (
                "Publish this meeting to the archive and apply "
                "the configured M4A retention rules?\n\n"
                f"Meeting:\n{run_dir.name}\n\n"
                f"Archive:\n{ARCHIVE_DIR}"
            ),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            ),
            QMessageBox.StandardButton.No,
        )

        if response != QMessageBox.StandardButton.Yes:
            return

        self.choose_transcribe_source_button.setEnabled(
            False
        )
        self.transcribe_run_button.setEnabled(
            False
        )
        self.transcribe_publish_button.setEnabled(
            False
        )
        self.transcribe_publish_button.setText(
            "Publishing…"
        )

        self.transcribe_progress_bar.setValue(
            0
        )
        self.transcribe_progress_detail.setText(
            "Starting Publish & Archive..."
        )
        self.transcribe_status_label.setText(
            "1. Intake — source recording selected ✓\n"
            "2. Transcribe — complete ✓\n"
            "3. Review — generated artifacts ready ✓\n"
            "4. Publish & Archive — running…"
        )

        self.transcribe_elapsed_timer.start()
        self.transcribe_elapsed_label.setText(
            "Elapsed: 00:00"
        )
        self.transcribe_elapsed_update_timer.start()

        self.publish_thread = QThread()
        self.publish_worker = PublishWorker(
            run_dir
        )
        self.publish_worker.moveToThread(
            self.publish_thread
        )

        self.publish_thread.started.connect(
            self.publish_worker.run
        )
        self.publish_worker.progress.connect(
            self._publish_progress
        )
        self.publish_worker.finished.connect(
            self._publish_finished
        )
        self.publish_worker.failed.connect(
            self._publish_failed
        )
        self.publish_worker.finished.connect(
            self.publish_thread.quit
        )
        self.publish_worker.failed.connect(
            self.publish_thread.quit
        )
        self.publish_thread.finished.connect(
            self.publish_worker.deleteLater
        )
        self.publish_thread.finished.connect(
            self.publish_thread.deleteLater
        )
        self.publish_thread.finished.connect(
            self._publish_thread_finished
        )

        self.publish_thread.start()

    def _publish_progress(
        self,
        message: str,
        percent: int,
    ):
        self.transcribe_progress_bar.setValue(
            percent
        )
        self.transcribe_progress_detail.setText(
            message
        )

    def _publish_finished(
        self,
        archived_path_text: str,
        result: dict,
    ):
        self._stop_transcribe_elapsed()

        archived_path = Path(
            archived_path_text
        )

        self.transcribe_progress_bar.setValue(
            100
        )
        self.transcribe_progress_detail.setText(
            f"Published successfully: {archived_path}"
        )
        self.transcribe_status_label.setText(
            "1. Intake — source recording selected ✓\n"
            "2. Transcribe — complete ✓\n"
            "3. Review — generated artifacts ready ✓\n"
            "4. Publish & Archive — complete ✓"
        )

        self.choose_transcribe_source_button.setEnabled(
            True
        )
        self.transcribe_run_button.setText(
            "Transcribe Again"
        )
        self.transcribe_run_button.setEnabled(
            True
        )
        self.transcribe_publish_button.setText(
            "Published"
        )
        self.transcribe_publish_button.setEnabled(
            False
        )

        # Rebuild the Meetings browser from the refreshed archive index.
        # The same logical meeting now resolves to the Published copy.
        self._load_meetings()
        self._sort_meetings(
            self.meeting_sort.currentText()
        )

        local_deleted = int(
            result.get(
                "local_retention", {}
            ).get("deleted", 0)
        )
        archive_deleted = int(
            result.get(
                "archived_retention", {}
            ).get("deleted", 0)
        )

        QMessageBox.information(
            self,
            "Publish & Archive Complete",
            (
                "The meeting was published successfully.\n\n"
                f"Archive folder:\n{archived_path}\n\n"
                "Retention cleanup:\n"
                f"• Local M4As removed: {local_deleted}\n"
                f"• Archived M4As removed: {archive_deleted}"
            ),
        )

    def _publish_failed(
        self,
        error: str,
    ):
        self._stop_transcribe_elapsed()

        self.transcribe_progress_detail.setText(
            "Publish & Archive failed."
        )
        self.transcribe_status_label.setText(
            "1. Intake — source recording selected ✓\n"
            "2. Transcribe — complete ✓\n"
            "3. Review — generated artifacts ready ✓\n"
            "4. Publish & Archive — failed ✕"
        )

        self.choose_transcribe_source_button.setEnabled(
            True
        )
        self.transcribe_run_button.setEnabled(
            True
        )
        self.transcribe_publish_button.setText(
            "Publish && Archive"
        )
        self.transcribe_publish_button.setEnabled(
            True
        )

        QMessageBox.warning(
            self,
            "Publish & Archive Failed",
            (
                f"{error}\n\n"
                "The local transcription run has been left in place."
            ),
        )

    def _publish_thread_finished(self):
        self.publish_worker = None
        self.publish_thread = None

    def _load_sessions(self):
        sessions_dir = (
            ARCHIVE_DIR / "query_sessions"
        )

        self.session_list.clear()

        entries = load_session_browser_entries(
            sessions_dir
        )

        if not entries:
            self.session_list.addItem(
                "No saved sessions"
            )
            return

        for entry in entries:
            item = QListWidgetItem(
                entry.label
            )
            item.setToolTip(
                entry.tooltip
            )
            self.session_list.addItem(
                item
            )

    def _create_dynamic_session(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(
            "New Dynamic Session"
        )

        layout = QVBoxLayout(dialog)

        explanation = QLabel(
            "Dynamic sessions re-run their saved "
            "criteria when refreshed. The history "
            "window is rolling, so a 90-day session "
            "always means the most recent 90 days."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()

        name_input = QLineEdit()
        name_input.setPlaceholderText(
            "Alex 1:1s"
        )
        form.addRow(
            "Session name:",
            name_input,
        )

        person_combo = QComboBox()
        person_combo.addItem(ANY_PERSON_LABEL)
        person_combo.addItems(
            available_people(load_meeting_index())
        )
        form.addRow(
            "Person:",
            person_combo,
        )

        title_input = QLineEdit()
        title_input.setPlaceholderText(
            "Optional, e.g. 1v1"
        )
        form.addRow(
            "Title contains:",
            title_input,
        )

        topic_input = QLineEdit()
        topic_input.setPlaceholderText(
            "Optional, e.g. Platform Alpha"
        )
        form.addRow(
            "Topic contains:",
            topic_input,
        )

        history_combo = QComboBox()
        history_combo.addItems(HISTORY_OPTIONS)
        history_combo.setCurrentText(
            DEFAULT_HISTORY_LABEL
        )
        form.addRow(
            "History window:",
            history_combo,
        )

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(
            dialog.accept
        )
        buttons.rejected.connect(
            dialog.reject
        )
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        session_name = (
            name_input.text().strip()
        )

        if not session_name:
            QMessageBox.warning(
                self,
                "Session Name Required",
                "Enter a name for the dynamic session.",
            )
            return

        sessions_dir = (
            ARCHIVE_DIR / "query_sessions"
        )

        existing_names = {
            path.stem.casefold()
            for path in sessions_dir.glob(
                "*.json"
            )
        }

        if (
            session_name.casefold()
            in existing_names
        ):
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named '{session_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return

        selection_criteria = build_create_criteria(
            person_text=person_combo.currentText(),
            title_text=title_input.text(),
            topic_text=topic_input.text(),
            history_label=history_combo.currentText(),
        )

        if not criteria_present(selection_criteria):
            QMessageBox.warning(
                self,
                "Criteria Required",
                (
                    "Choose at least one criterion or "
                    "a rolling history window."
                ),
            )
            return

        try:
            create_summary = create_dynamic_session_action(
                session_name=session_name,
                criteria=selection_criteria,
                sessions_dir=sessions_dir,
                select_meetings=select_session_meetings,
                save_session=save_chat_session,
            )
        except DuplicateSessionNameError:
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named '{session_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return
        except CriteriaRequiredError as exc:
            QMessageBox.warning(
                self,
                "Criteria Required",
                str(exc),
            )
            return
        except NoMatchingMeetingsError:
            QMessageBox.warning(
                self,
                "No Matching Meetings",
                (
                    "No meetings currently "
                    "match those criteria. The session "
                    "was not created."
                ),
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Create Session",
                str(exc),
            )
            return

        self._load_sessions()

        for index in range(
            self.session_list.count()
        ):
            item = self.session_list.item(
                index
            )

            item_session_name = (
                item.text()
                .splitlines()[0]
                .strip()
            )

            if item_session_name == session_name:
                self.session_list.setCurrentItem(
                    item
                )
                break

        QMessageBox.information(
            self,
            "Dynamic Session Created",
            (
                f"Created '{session_name}' with "
                f"{create_summary.meeting_count} matching meetings."
            ),
        )

    def _edit_selected_session_criteria(self):
        current = self.session_list.currentItem()

        if current is None:
            return

        session_name = (
            current.text()
            .splitlines()[0]
            .strip()
        )

        if (
            not session_name
            or session_name == "No saved sessions"
        ):
            return

        try:
            session = load_chat_session(
                session_name
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Load Session",
                str(exc),
            )
            return

        selection_criteria = (
            session.get(
                "selection_criteria"
            )
            or {}
        )

        if not selection_criteria:
            QMessageBox.information(
                self,
                "Fixed Session",
                (
                    "This is a fixed/manual session and "
                    "does not have editable selection "
                    "criteria."
                ),
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "Edit Dynamic Session Criteria"
        )

        layout = QVBoxLayout(dialog)

        explanation = QLabel(
            "Changing the criteria recalculates which "
            "meetings belong to this session. Existing "
            "conversation history is preserved."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()

        person_combo = QComboBox()
        person_combo.addItem(ANY_PERSON_LABEL)

        current_person = selection_criteria.get(
            "person"
        )
        person_combo.addItems(
            available_people(
                load_meeting_index(),
                current_person=current_person,
            )
        )

        if current_person:
            person_combo.setCurrentText(
                current_person
            )

        form.addRow(
            "Person:",
            person_combo,
        )

        title_input = QLineEdit()
        title_input.setText(
            selection_criteria.get(
                "title"
            )
            or ""
        )
        title_input.setPlaceholderText(
            "Optional, e.g. 1v1"
        )
        form.addRow(
            "Title contains:",
            title_input,
        )

        topic_input = QLineEdit()
        topic_input.setText(
            selection_criteria.get(
                "topic"
            )
            or ""
        )
        topic_input.setPlaceholderText(
            "Optional, e.g. Platform Alpha"
        )
        form.addRow(
            "Topic contains:",
            topic_input,
        )

        history_combo = QComboBox()

        saved_start_date = selection_criteria.get(
            "start_date"
        )
        saved_end_date = selection_criteria.get(
            "end_date"
        )

        (
            history_options,
            selected_history_label,
            custom_range_label,
        ) = edit_history_state(selection_criteria)
        history_combo.addItems(history_options)
        history_combo.setCurrentText(
            selected_history_label
        )

        form.addRow(
            "History window:",
            history_combo,
        )

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(
            dialog.accept
        )
        buttons.rejected.connect(
            dialog.reject
        )
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_criteria = build_edit_criteria(
            person_text=person_combo.currentText(),
            title_text=title_input.text(),
            topic_text=topic_input.text(),
            selected_history_label=history_combo.currentText(),
            custom_range_label=custom_range_label,
            saved_start_date=saved_start_date,
            saved_end_date=saved_end_date,
        )

        if not criteria_present(new_criteria):
            QMessageBox.warning(
                self,
                "Criteria Required",
                (
                    "Choose at least one criterion or "
                    "a rolling history window."
                ),
            )
            return

        try:
            edit_summary = edit_dynamic_session_action(
                session_name=session_name,
                session=session,
                criteria=new_criteria,
                select_meetings=select_session_meetings,
                save_session=save_chat_session,
            )
        except CriteriaRequiredError as exc:
            QMessageBox.warning(
                self,
                "Criteria Required",
                str(exc),
            )
            return
        except NoMatchingMeetingsError:
            QMessageBox.warning(
                self,
                "No Matching Meetings",
                (
                    "No meetings currently match the "
                    "edited criteria. The session was not "
                    "changed."
                ),
            )
            return
        except FixedSessionError as exc:
            QMessageBox.information(
                self,
                "Fixed Session",
                str(exc),
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Edit Criteria",
                str(exc),
            )
            return

        self._load_sessions()

        for index in range(
            self.session_list.count()
        ):
            item = self.session_list.item(
                index
            )

            item_session_name = (
                item.text()
                .splitlines()[0]
                .strip()
            )

            if item_session_name == session_name:
                self.session_list.setCurrentItem(
                    item
                )
                break

        QMessageBox.information(
            self,
            "Criteria Updated",
            (
                f"Updated '{session_name}'.\n\n"
                f"Added: {edit_summary.added}\n"
                f"Removed: {edit_summary.removed}\n"
                f"Unchanged: {edit_summary.unchanged}"
            ),
        )

    def _rename_selected_session(self):
        current = self.session_list.currentItem()

        if current is None:
            return

        old_name = (
            current.text()
            .splitlines()[0]
            .strip()
        )

        if (
            not old_name
            or old_name == "No saved sessions"
        ):
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename Session",
            "New session name:",
            text=old_name,
        )

        if not ok:
            return

        new_name = new_name.strip()

        if (
            not new_name
            or new_name == old_name
        ):
            return

        sessions_dir = (
            ARCHIVE_DIR / "query_sessions"
        )

        existing_names = {
            path.stem.casefold()
            for path in sessions_dir.glob(
                "*.json"
            )
            if path.stem.casefold()
            != old_name.casefold()
        }

        if (
            new_name.casefold()
            in existing_names
        ):
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named "
                    f"'{new_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return

        try:
            new_name = rename_session_action(
                old_name=old_name,
                new_name=new_name,
                sessions_dir=sessions_dir,
                rename=rename_chat_session,
            )
        except DuplicateSessionNameError:
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named '{new_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Rename Session",
                str(exc),
            )
            return

        self._load_sessions()

        for index in range(
            self.session_list.count()
        ):
            item = self.session_list.item(
                index
            )

            item_session_name = (
                item.text()
                .splitlines()[0]
                .strip()
            )

            if item_session_name == new_name:
                self.session_list.setCurrentItem(
                    item
                )
                break

    def _refresh_selected_session(self):
        current = self.session_list.currentItem()

        if current is None:
            return

        session_name = (
            current.text()
            .splitlines()[0]
            .strip()
        )

        if (
            not session_name
            or session_name == "No saved sessions"
        ):
            return

        try:
            session = load_chat_session(
                session_name
            )
            refresh_summary = refresh_dynamic_session_action(
                session_name=session_name,
                session=session,
                resume_session=resume_saved_session,
                save_session=save_chat_session,
            )
        except FixedSessionError as exc:
            QMessageBox.information(
                self,
                "Fixed Session",
                str(exc),
            )
            return
        except SessionAlreadyCurrent as exc:
            QMessageBox.information(
                self,
                "Session Already Current",
                (
                    "No meeting changes were found.\n\n"
                    f"Unchanged: {exc.unchanged}"
                ),
            )
            return
        except NoMatchingMeetingsError:
            QMessageBox.warning(
                self,
                "No Matching Meetings",
                (
                    "The saved criteria currently match "
                    "no meetings. The session was not "
                    "changed."
                ),
            )
            return
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Refresh Session",
                str(exc),
            )
            return

        self._load_sessions()

        for index in range(
            self.session_list.count()
        ):
            item = self.session_list.item(
                index
            )

            item_session_name = (
                item.text()
                .splitlines()[0]
                .strip()
            )

            if item_session_name == session_name:
                self.session_list.setCurrentItem(
                    item
                )
                break

        QMessageBox.information(
            self,
            "Session Refreshed",
            (
                f"Added: {refresh_summary.added}\n"
                f"Removed: {refresh_summary.removed}\n"
                f"Unchanged: {refresh_summary.unchanged}"
            ),
        )

    def _delete_selected_session(self):
        current = self.session_list.currentItem()

        if current is None:
            return

        session_name = (
            current.text()
            .splitlines()[0]
            .strip()
        ) 

        if (
            not session_name
            or session_name == "No saved sessions"
        ):
            return

        response = QMessageBox.question(
            self,
            "Delete Session",
            (
                f"Delete session "
                f"'{session_name}'?\n\n"
                f"This deletes only the saved session. "
                f"The archived meetings are not affected."
            ),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            ),
            QMessageBox.StandardButton.No,
        )

        if (
            response
            != QMessageBox.StandardButton.Yes
        ):
            return

        try:
            delete_session_action(
                session_name=session_name,
                delete=delete_chat_session,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Unable to Delete Session",
                str(exc),
            )
            return

        self.current_session = None
        self.current_context = None
        self.current_meeting_dirs = []

        self.context_view.clear()
        self.chat_view.clear()
        self.chat_input.clear()

        self._load_sessions()

    def _load_meetings(self):
        self.meeting_list.clear()

        entries = build_meeting_browser_entries(
            load_meeting_index()
        )
        entries.sort(
            key=lambda entry: entry.meeting_run,
            reverse=True,
        )

        unpublished_count = count_unpublished(
            entries
        )

        if unpublished_count:
            noun = (
                "meeting"
                if unpublished_count == 1
                else "meetings"
            )
            verb = (
                "is"
                if unpublished_count == 1
                else "are"
            )
            self.unpublished_meeting_label.setText(
                f"{unpublished_count} transcribed {noun} "
                f"{verb} waiting to be published."
            )

            reminder_font = (
                self.unpublished_meeting_label.font()
            )
            reminder_font.setBold(True)
            self.unpublished_meeting_label.setFont(
                reminder_font
            )
            if hasattr(
                self,
                "view_unpublished_meetings_button",
            ):
                self.view_unpublished_meetings_button.setVisible(
                    True
                )
        else:
            self.unpublished_meeting_label.setText(
                "No transcribed meetings are waiting to be published."
            )
            if hasattr(
                self,
                "view_unpublished_meetings_button",
            ):
                self.view_unpublished_meetings_button.setVisible(
                    False
                )

            reminder_font = (
                self.unpublished_meeting_label.font()
            )
            reminder_font.setBold(False)
            self.unpublished_meeting_label.setFont(
                reminder_font
            )

        for entry in entries:
            item = QListWidgetItem(
                entry.label
            )

            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
            )

            item.setCheckState(
                Qt.CheckState.Unchecked
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                entry.meeting_run,
            )
            item.setData(
                Qt.ItemDataRole.UserRole + 1,
                entry.search_text,
            )
            item.setData(
                Qt.ItemDataRole.UserRole + 2,
                entry.meeting_date,
            )
            item.setData(
                Qt.ItemDataRole.UserRole + 3,
                entry.publish_status,
            )
            item.setData(
                Qt.ItemDataRole.UserRole + 4,
                entry.preview_markdown,
            )

            self.meeting_list.addItem(
                item
            )

        self.selected_meeting_label.setText(
            "Selected: 0"
        )

        if hasattr(self, "meeting_publish_button"):
            self._update_meeting_publish_action()

    def _meeting_selection_rows(self):
        rows = []

        for index in range(self.meeting_list.count()):
            item = self.meeting_list.item(index)
            rows.append(
                MeetingSelectionRow(
                    meeting_run=item.data(
                        Qt.ItemDataRole.UserRole
                    ),
                    checked=(
                        item.checkState()
                        == Qt.CheckState.Checked
                    ),
                    visible=not item.isHidden(),
                )
            )

        return rows

    def _meeting_selection_changed(
        self,
        item: QListWidgetItem,
    ):
        self.selected_meeting_label.setText(
            selected_count_label(
                self._meeting_selection_rows()
            )
        )

        self._update_context_stale_state()

    def _clear_meeting_selection(self):
        for index in range(
            self.meeting_list.count()
        ):
            item = self.meeting_list.item(
                index
            )

            if (
                item.checkState()
                == Qt.CheckState.Checked
            ):
                item.setCheckState(
                    Qt.CheckState.Unchecked
                )

    def _select_visible_meetings(self):
        for index in range(
            self.meeting_list.count()
        ):
            item = self.meeting_list.item(
                index
            )

            if not item.isHidden():
                item.setCheckState(
                    Qt.CheckState.Checked
                )

    def _clear_visible_meetings(self):
        for index in range(
            self.meeting_list.count()
        ):
            item = self.meeting_list.item(
                index
            )

            if not item.isHidden():
                item.setCheckState(
                    Qt.CheckState.Unchecked
                )

    def _update_meeting_context_markers(self):
        context_runs = set()

        if self.current_session is not None:
            context_runs = set(
                self.current_session.get(
                    "meeting_runs",
                    [],
                )
            )

        for index in range(
            self.meeting_list.count()
        ):
            item = self.meeting_list.item(
                index
            )

            meeting_run = item.data(
                Qt.ItemDataRole.UserRole
            )

            item_in_context = in_context(
                meeting_run,
                context_runs,
            )

            font = item.font()
            font.setBold(item_in_context)
            item.setFont(font)

            if item_in_context:
                item.setToolTip(
                    "In current ad hoc context"
                )
            else:
                item.setToolTip("")

    def _update_context_stale_state(self):
        if (
            self.current_session is None
            or self.current_context is None
        ):
            return

        context_runs = self.current_session.get(
            "meeting_runs",
            [],
        )

        checked_runs = selected_runs(
            self._meeting_selection_rows()
        )

        self.context_label.setText(
            context_status_label(
                context_runs,
                checked_runs,
            )
        )

    def _preview_meeting(
        self,
        current,
        previous,
    ):
        if current is None:
            self.meeting_preview.clear()
            return

        preview_markdown = current.data(
            Qt.ItemDataRole.UserRole + 4
        )

        if not preview_markdown:
            self.meeting_preview.clear()
            return

        self.meeting_preview.setMarkdown(
            preview_markdown
        )

    def _update_meeting_publish_action(
        self,
        current=None,
        previous=None,
    ):
        if not hasattr(
            self,
            "meeting_publish_button",
        ):
            return

        publishing = (
            getattr(self, "publish_thread", None) is not None
            and self.publish_thread.isRunning()
        )

        if publishing:
            self.meeting_publish_button.setEnabled(
                False
            )
            return

        item = (
            current
            if current is not None
            else self.meeting_list.currentItem()
        )

        if item is None:
            self.meeting_publish_button.setEnabled(
                False
            )
            self.meeting_publish_button.setText(
                "Publish && Archive"
            )
            self.meeting_publish_status_label.setText(
                "Select an Unpublished meeting to publish."
            )
            return

        publish_status = item.data(
            Qt.ItemDataRole.UserRole + 3
        ) or "Published"

        is_unpublished = (
            publish_status == "Unpublished"
        )

        self.meeting_publish_button.setText(
            "Publish && Archive"
        )
        self.meeting_publish_button.setEnabled(
            is_unpublished
        )

        if is_unpublished:
            self.meeting_publish_status_label.setText(
                "Ready to publish this local meeting."
            )
        else:
            self.meeting_publish_status_label.setText(
                "This meeting is already Published."
            )

    def _update_meeting_publish_elapsed(self):
        if not self.meeting_publish_elapsed_timer.isValid():
            return

        elapsed_seconds = (
            self.meeting_publish_elapsed_timer.elapsed()
            // 1000
        )
        minutes, seconds = divmod(
            elapsed_seconds,
            60,
        )

        base_text = getattr(
            self,
            "meeting_publish_progress_text",
            "Publishing & archiving...",
        )
        self.meeting_publish_status_label.setText(
            f"{base_text}  Elapsed: {minutes:02d}:{seconds:02d}"
        )

    def _stop_meeting_publish_elapsed(self):
        self.meeting_publish_elapsed_update_timer.stop()
        self._update_meeting_publish_elapsed()

    def _start_selected_meeting_publish(self):
        item = self.meeting_list.currentItem()

        if item is None:
            return

        publish_status = item.data(
            Qt.ItemDataRole.UserRole + 3
        ) or "Published"

        if publish_status != "Unpublished":
            return

        meeting_run = item.data(
            Qt.ItemDataRole.UserRole
        )

        meeting = next(
            (
                record
                for record in load_meeting_index()
                if record.get("meeting_run")
                == meeting_run
            ),
            None,
        )

        if not meeting:
            QMessageBox.warning(
                self,
                "Meeting Not Found",
                "The selected meeting could not be resolved.",
            )
            return

        location = meeting.get("location")
        run_dir = Path(location) if location else None

        if run_dir is None or not run_dir.exists():
            QMessageBox.warning(
                self,
                "Local Meeting Not Found",
                (
                    "The completed local meeting folder no longer "
                    "exists:\n\n"
                    f"{location or meeting_run}"
                ),
            )
            return

        if not ARCHIVE_DIR.exists():
            QMessageBox.warning(
                self,
                "Archive Unavailable",
                (
                    "The configured archive/NAS is not available:\n\n"
                    f"{ARCHIVE_DIR}"
                ),
            )
            return

        if (ARCHIVE_DIR / run_dir.name).exists():
            QMessageBox.warning(
                self,
                "Already Published",
                (
                    "An archive folder already exists for this "
                    "meeting:\n\n"
                    f"{ARCHIVE_DIR / run_dir.name}"
                ),
            )
            self._load_meetings()
            return

        if (
            self.publish_thread is not None
            and self.publish_thread.isRunning()
        ):
            return

        response = QMessageBox.question(
            self,
            "Publish & Archive Meeting",
            (
                "Publish this selected meeting and apply the "
                "configured M4A retention rules?\n\n"
                f"Meeting:\n{run_dir.name}\n\n"
                f"Archive:\n{ARCHIVE_DIR}"
            ),
            (
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            ),
            QMessageBox.StandardButton.No,
        )

        if response != QMessageBox.StandardButton.Yes:
            return

        self.meeting_publish_button.setEnabled(False)
        self.meeting_publish_button.setText("Publishing…")
        self.meeting_publish_progress_text = (
            "Starting Publish & Archive..."
        )
        self.meeting_publish_status_label.setText(
            self.meeting_publish_progress_text
        )
        self.meeting_publish_elapsed_timer.start()
        self.meeting_publish_elapsed_update_timer.start()

        self.publish_thread = QThread()
        self.publish_worker = PublishWorker(run_dir)
        self.publish_worker.moveToThread(
            self.publish_thread
        )
        self.publish_thread.started.connect(
            self.publish_worker.run
        )
        self.publish_worker.progress.connect(
            self._selected_meeting_publish_progress
        )
        self.publish_worker.finished.connect(
            self._selected_meeting_publish_finished
        )
        self.publish_worker.failed.connect(
            self._selected_meeting_publish_failed
        )
        self.publish_worker.finished.connect(
            self.publish_thread.quit
        )
        self.publish_worker.failed.connect(
            self.publish_thread.quit
        )
        self.publish_thread.finished.connect(
            self.publish_worker.deleteLater
        )
        self.publish_thread.finished.connect(
            self.publish_thread.deleteLater
        )
        self.publish_thread.finished.connect(
            self._selected_meeting_publish_thread_finished
        )
        self.publish_thread.start()

    def _selected_meeting_publish_progress(
        self,
        message: str,
        percent: int,
    ):
        self.meeting_publish_progress_text = (
            f"{message} ({percent}%)"
        )
        self._update_meeting_publish_elapsed()

    def _selected_meeting_publish_finished(
        self,
        archived_path_text: str,
        result: dict,
    ):
        self._stop_meeting_publish_elapsed()
        archived_path = Path(archived_path_text)

        self.meeting_publish_progress_text = (
            "Published successfully."
        )
        self._update_meeting_publish_elapsed()

        local_deleted = int(
            result.get("local_retention", {}).get(
                "deleted",
                0,
            )
        )
        archive_deleted = int(
            result.get("archived_retention", {}).get(
                "deleted",
                0,
            )
        )

        self._load_meetings()
        self._sort_meetings(
            self.meeting_sort.currentText()
        )

        QMessageBox.information(
            self,
            "Publish & Archive Complete",
            (
                "The meeting was published successfully.\n\n"
                f"Archive folder:\n{archived_path}\n\n"
                "Retention cleanup:\n"
                f"• Local M4As removed: {local_deleted}\n"
                f"• Archived M4As removed: {archive_deleted}"
            ),
        )

    def _selected_meeting_publish_failed(
        self,
        error: str,
    ):
        self._stop_meeting_publish_elapsed()
        self.meeting_publish_progress_text = (
            "Publish & Archive failed."
        )
        self._update_meeting_publish_elapsed()
        self.meeting_publish_button.setText(
            "Publish && Archive"
        )
        self.meeting_publish_button.setEnabled(True)

        QMessageBox.warning(
            self,
            "Publish & Archive Failed",
            (
                f"{error}\n\n"
                "The local transcription run has been left in place."
            ),
        )

    def _selected_meeting_publish_thread_finished(self):
        self.publish_worker = None
        self.publish_thread = None
        self._update_meeting_publish_action()

    def _filter_meetings(
        self,
        _value=None,
    ):
        search_text = (
            self.meeting_search
            .text()
            .strip()
            .lower()
        )

        date_filter = (
            self.meeting_date_filter
            .currentText()
        )

        status_filter = (
            self.meeting_status_filter
            .currentText()
        )

        custom_from = None
        custom_to = None

        if date_filter == "Custom range":
            custom_from = (
                self.meeting_from_date
                .date()
                .toPython()
            )
            custom_to = (
                self.meeting_to_date
                .date()
                .toPython()
            )

        for index in range(
            self.meeting_list.count()
        ):
            item = self.meeting_list.item(
                index
            )

            visible = meeting_fields_match_filters(
                meeting_search_text=(
                    item.data(
                        Qt.ItemDataRole.UserRole + 1
                    )
                    or ""
                ),
                meeting_date_text=(
                    item.data(
                        Qt.ItemDataRole.UserRole + 2
                    )
                    or ""
                ),
                publish_status=(
                    item.data(
                        Qt.ItemDataRole.UserRole + 3
                    )
                    or "Published"
                ),
                search_text=search_text,
                date_filter=date_filter,
                status_filter=status_filter,
                custom_from=custom_from,
                custom_to=custom_to,
            )

            item.setHidden(
                not visible
            )

    def _view_unpublished_meetings(self):
        self.meeting_status_filter.setCurrentText(
            "Unpublished"
        )
        self.left_tabs.setCurrentIndex(
            1
        )
        self._filter_meetings()

    def _date_filter_changed(
        self,
        value: str,
    ):
        self.custom_date_widget.setVisible(
            value == "Custom range"
        )

        self._filter_meetings()

    def _sort_meetings(
        self,
        sort_mode: str,
    ):
        items = []

        while self.meeting_list.count():
            items.append(
                self.meeting_list.takeItem(0)
            )

        if sort_mode == "Newest first":
            items.sort(
                key=lambda item: item.data(
                    Qt.ItemDataRole.UserRole
                ),
                reverse=True,
            )

        elif sort_mode == "Oldest first":
            items.sort(
                key=lambda item: item.data(
                    Qt.ItemDataRole.UserRole
                ),
            )

        elif sort_mode == "Title A-Z":
            items.sort(
                key=lambda item: (
                    item.text()
                    .splitlines()[-1]
                    .lower()
                ),
            )

        for item in items:
            self.meeting_list.addItem(
                item
            )

        self._filter_meetings()

    def _render_prep(
        self,
        prep: dict,
        heading: str,
        selection_criteria: dict | None = None,
    ):
        self.context_view.setPlainText(
            format_session_prep(
                prep,
                heading,
                selection_criteria=selection_criteria,
            )
        )

    def _build_selected_meeting_context(self):
        checked_runs = selected_runs(
            self._meeting_selection_rows()
        )

        try:
            bundle = build_ad_hoc_context(
                checked_runs,
                load_meeting_index(),
            )
        except NoMeetingsSelectedError as exc:
            self.context_view.setPlainText(str(exc))
            return
        except NoLoadableMeetingsError as exc:
            self.context_view.setPlainText(str(exc))
            return
        except Exception as exc:
            self.context_view.setPlainText(
                "Unable to build meeting context:\n\n"
                + str(exc)
            )
            return

        self.current_context = bundle["context"]
        self.current_meeting_dirs = bundle["meeting_dirs"]
        self.current_session = bundle["session"]

        self.chat_view.clear()
        self.chat_input.clear()

        self._render_prep(
            bundle["prep"],
            "AD HOC MEETING CONTEXT",
        )

        self._update_meeting_context_markers()
        self._update_context_stale_state()
        self.save_session_button.setEnabled(True)

    def _save_selected_as_session(self):
        if not self.current_context:
            self.context_view.setPlainText(
                "Build a meeting context first."
            )
            return

        if not self.current_session:
            self.context_view.setPlainText(
                "Build a meeting context first."
            )
            return

        session_name, ok = (
            QInputDialog.getText(
                self,
                "Save Session",
                "Session name:",
            )
        )

        if not ok:
            return

        session_name = (
            session_name.strip()
        )

        if not session_name:
            return

        sessions_dir = (
            ARCHIVE_DIR / "query_sessions"
        )

        existing_names = {
            path.stem.casefold()
            for path in sessions_dir.glob(
                "*.json"
            )
        }

        if (
            session_name.casefold()
            in existing_names
        ):
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named "
                    f"'{session_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return

        history = (
            self.current_session.get(
                "conversation_history",
                [],
            )
        )

        try:
            session_name = save_fixed_session_action(
                session_name=session_name,
                meeting_dirs=self.current_meeting_dirs,
                history=history,
                sessions_dir=sessions_dir,
                save_session=save_chat_session,
            )
        except DuplicateSessionNameError:
            QMessageBox.warning(
                self,
                "Session Already Exists",
                (
                    f"A session named '{session_name}' "
                    f"already exists.\n\n"
                    f"Choose a different name."
                ),
            )
            return
        except Exception as exc:
            self.context_view.setPlainText(
                "Unable to save session:\n\n"
                + str(exc)
            )
            return

        self.current_session[
            "session_name"
        ] = session_name

        self._load_sessions()

        # Switch to Sessions.
        self.left_tabs.setCurrentIndex(
            2
        )

        # Select the newly created session.
        for index in range(
            self.session_list.count()
        ):
            item = self.session_list.item(
                index
            )

            item_session_name = (
                item.text()
                .splitlines()[0]
                .strip()
            )

            if (
                item_session_name
                == session_name
            ):
                self.session_list.setCurrentItem(
                    item
                )
                break

    def _left_tab_changed(
        self,
        index: int,
    ):
        tab_name = (
            self.left_tabs.tabText(
                index
            )
        )

        if tab_name == "Transcribe":
            self.transcribe_center_panel.setVisible(
                True
            )
            self.knowledge_center_panel.setVisible(
                False
            )
            return

        self.transcribe_center_panel.setVisible(
            False
        )
        self.knowledge_center_panel.setVisible(
            True
        )

        if tab_name == "Meetings":
            self.context_label.setText(
                "Selected Meetings Context"
            )

            self.current_session = None
            self.current_context = None

            self.current_meeting_dirs = []

            self.save_session_button.setEnabled(
                False
            )

            self._update_meeting_context_markers()
            self.context_view.clear()
            self.chat_view.clear()
            self.chat_input.clear()

            return

        if tab_name == "Sessions":
            self.context_label.setText(
                "Session Context"
            )
            current = (
                self.session_list.currentItem()
            )

            if current is not None:
                self._session_selected(
                    current,
                    None,
                )

    def _session_selected(
        self,
        current,
        previous,
    ):
        if current is None:
            self.edit_session_criteria_button.setEnabled(
                False
            )
            self.refresh_session_button.setEnabled(
                False
            )
            self.context_view.clear()
            self.chat_view.clear()
            return

        session_name = (
            current.text()
            .splitlines()[0]
            .strip()
        )

        try:
            bundle = build_saved_session_context(
                session_name
            )

            self.current_session = bundle["session"]
            self.current_meeting_dirs = bundle["meeting_dirs"]
            self.current_context = bundle["context"]
            selection_criteria = bundle["selection_criteria"]
            prep = bundle["prep"]

            self.edit_session_criteria_button.setEnabled(
                bool(selection_criteria)
            )
            self.refresh_session_button.setEnabled(
                bool(selection_criteria)
            )

        except Exception as exc:
            self.edit_session_criteria_button.setEnabled(
                False
            )
            self.refresh_session_button.setEnabled(
                False
            )
            self.context_view.setPlainText(
                f"Unable to build meeting prep:\n\n"
                f"{exc}"
            )
            return

        self._render_prep(
            prep,
            f"SESSION: {session_name}",
            selection_criteria=selection_criteria,
        )

        self._render_conversation()

    def _render_conversation(self):
        history = []
        if self.current_session:
            history = self.current_session.get(
                "conversation_history",
                [],
            )

        markdown = render_conversation_markdown(
            history
        )

        if markdown:
            self.chat_view.setMarkdown(markdown)
        else:
            self.chat_view.clear()

        scrollbar = (
            self.chat_view
            .verticalScrollBar()
        )
        scrollbar.setValue(
            scrollbar.maximum()
        )

    def _open_preferences(self):
        settings = load_app_settings()

        output_path = Path(
            settings.get("output_dir")
            or OUTPUT_DIR
        ).expanduser()

        archive_path = Path(
            settings.get("archive_dir")
            or ARCHIVE_DIR
        ).expanduser()

        llm_model = str(
            settings.get("llm_model")
            or LLM_MODEL
        ).strip()

        llm_context_size = int(
            settings.get("llm_context_size")
            if settings.get("llm_context_size")
            is not None
            else LLM_CONTEXT_SIZE
        )

        retention_days = int(
            settings.get("m4a_retention_days")
            or M4A_RETENTION_DAYS
        )

        archived_retention_days = int(
            settings.get("archived_m4a_retention_days")
            if settings.get("archived_m4a_retention_days")
            is not None
            else ARCHIVED_M4A_RETENTION_DAYS
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            "Meeting Transcriber Preferences"
        )
        dialog.resize(
            980,
            430,
        )

        layout = QVBoxLayout(dialog)

        note = QLabel(
            "Storage paths, Ollama model, and Ollama context size "
            "are loaded when Meeting Transcriber starts. Restart "
            "the app after changing those settings."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()

        output_input = QLineEdit(
            str(output_path)
        )
        output_input.setMinimumWidth(
            520
        )
        output_browse = QPushButton(
            "Browse…"
        )
        output_row = QWidget()
        output_row_layout = QHBoxLayout(
            output_row
        )
        output_row_layout.setContentsMargins(
            0, 0, 0, 0
        )
        output_row_layout.addWidget(
            output_input
        )
        output_row_layout.addWidget(
            output_browse
        )

        form.addRow(
            "Output / Working Folder",
            output_row,
        )

        archive_input = QLineEdit(
            str(archive_path)
        )
        archive_input.setMinimumWidth(
            520
        )
        archive_browse = QPushButton(
            "Browse…"
        )
        archive_row = QWidget()
        archive_row_layout = QHBoxLayout(
            archive_row
        )
        archive_row_layout.setContentsMargins(
            0, 0, 0, 0
        )
        archive_row_layout.addWidget(
            archive_input
        )
        archive_row_layout.addWidget(
            archive_browse
        )

        form.addRow(
            "Archive / NAS Folder",
            archive_row,
        )

        archive_status = QLabel()
        form.addRow(
            "Archive status",
            archive_status,
        )

        model_combo = QComboBox()
        model_combo.setEditable(True)
        model_combo.setMinimumWidth(
            420
        )

        refresh_models_button = QPushButton(
            "Refresh Models"
        )

        model_row = QWidget()
        model_row_layout = QHBoxLayout(
            model_row
        )
        model_row_layout.setContentsMargins(
            0, 0, 0, 0
        )
        model_row_layout.addWidget(
            model_combo
        )
        model_row_layout.addWidget(
            refresh_models_button
        )

        form.addRow(
            "Ollama Model",
            model_row,
        )

        model_status = QLabel()
        form.addRow(
            "Model status",
            model_status,
        )

        context_size_combo = QComboBox()
        for label, value in CONTEXT_SIZE_OPTIONS:
            context_size_combo.addItem(label, value)

        (
            context_size_data,
            custom_context_value,
            _,
        ) = context_size_state(llm_context_size)
        context_size_combo.setCurrentIndex(
            context_size_combo.findData(context_size_data)
        )

        custom_context_size = QSpinBox()
        custom_context_size.setRange(
            1024,
            262144,
        )
        custom_context_size.setSingleStep(
            1024
        )
        custom_context_size.setSuffix(
            " tokens"
        )
        custom_context_size.setValue(
            custom_context_value
        )

        form.addRow(
            "Ollama Context Size",
            context_size_combo,
        )
        form.addRow(
            "Custom Context Size",
            custom_context_size,
        )
        custom_context_label = (
            form.labelForField(
                custom_context_size
            )
        )

        context_note = QLabel(
            "Model default leaves Ollama's context setting unchanged. "
            "Choosing a size sends that num_ctx value to Ollama and "
            "also gives Auto a hard context ceiling."
        )
        context_note.setWordWrap(True)
        context_note.setMinimumHeight(
            42
        )
        context_note.setContentsMargins(
            0,
            6,
            0,
            10,
        )
        form.addRow(
            context_note
        )

        installed_models: list[str] = []
        model_discovery_error: str | None = None

        retention_input = QSpinBox()
        retention_input.setRange(
            1,
            3650,
        )
        retention_input.setValue(
            retention_days
        )
        retention_input.setSuffix(
            " days"
        )
        form.addRow(
            "Local M4A Retention",
            retention_input,
        )

        archived_retention_input = QSpinBox()
        archived_retention_input.setRange(
            0,
            3650,
        )
        archived_retention_input.setValue(
            archived_retention_days
        )
        archived_retention_input.setSuffix(
            " days"
        )
        archived_retention_input.setSpecialValueText(
            "Forever"
        )
        form.addRow(
            "Archived M4A Retention",
            archived_retention_input,
        )

        layout.addLayout(form)

        archive_note = QLabel(
            "Publish archives the original M4A with the meeting "
            "artifacts. Local M4As are kept for the configured "
            "local retention period after the archived source is "
            "verified. Archived M4A retention controls when the "
            "NAS source audio may be removed; choose Forever to "
            "keep archived source recordings indefinitely. Derived "
            "meeting artifacts are not removed by audio retention."
        )
        archive_note.setWordWrap(True)
        layout.addWidget(archive_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)

        def update_model_status():
            model_status.setText(
                model_status_text(
                    model_combo.currentText(),
                    installed_models,
                    model_discovery_error,
                )
            )

        def refresh_installed_models():
            nonlocal installed_models
            nonlocal model_discovery_error

            current_model = (
                model_combo.currentText().strip()
                or llm_model
            )

            (
                installed_models,
                model_discovery_error,
            ) = discover_installed_ollama_models()

            model_combo.blockSignals(True)
            model_combo.clear()

            for model_name in merge_model_choices(
                installed_models,
                current_model,
            ):
                model_combo.addItem(model_name)

            model_combo.setCurrentText(
                current_model
            )
            model_combo.blockSignals(False)

            update_model_status()

        def choose_output_folder():
            selected = QFileDialog.getExistingDirectory(
                dialog,
                "Choose Output / Working Folder",
                output_input.text()
                or str(Path.home()),
            )
            if selected:
                output_input.setText(selected)

        def choose_archive_folder():
            selected = QFileDialog.getExistingDirectory(
                dialog,
                "Choose Archive / NAS Folder",
                archive_input.text()
                or str(Path.home()),
            )
            if selected:
                archive_input.setText(selected)

        def update_archive_status():
            archive_status.setText(
                archive_status_text(archive_input.text())
            )

        def save_preferences():
            raw_output = (
                output_input.text().strip()
            )
            raw_archive = (
                archive_input.text().strip()
            )
            new_model = (
                model_combo.currentText().strip()
            )

            new_context_size = selected_context_size(
                context_size_combo.currentData(),
                custom_context_size.value(),
            )

            new_retention_days = (
                retention_input.value()
            )
            new_archived_retention_days = (
                archived_retention_input.value()
            )

            validation_error = validate_preferences(
                raw_output,
                raw_archive,
                new_model,
            )
            if validation_error is not None:
                QMessageBox.warning(
                    dialog,
                    validation_error.title,
                    validation_error.message,
                )
                return

            if (
                installed_models
                and new_model not in installed_models
            ):
                response = QMessageBox.question(
                    dialog,
                    "Model Not Detected",
                    (
                        f"'{new_model}' was not found in the "
                        "currently installed Ollama models.\n\n"
                        "Save it anyway?"
                    ),
                    (
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                    ),
                    QMessageBox.StandardButton.No,
                )

                if (
                    response
                    != QMessageBox.StandardButton.Yes
                ):
                    return

            new_output = Path(
                raw_output
            ).expanduser()
            new_archive = Path(
                raw_archive
            ).expanduser()

            if not new_output.exists():
                response = QMessageBox.question(
                    dialog,
                    "Create Output Folder",
                    (
                        f"The output folder does not exist:\n\n"
                        f"{new_output}\n\n"
                        "Create it now?"
                    ),
                    (
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No
                    ),
                    QMessageBox.StandardButton.Yes,
                )

                if (
                    response
                    != QMessageBox.StandardButton.Yes
                ):
                    return

                try:
                    new_output.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                except OSError as exc:
                    QMessageBox.warning(
                        dialog,
                        "Unable to Create Output Folder",
                        str(exc),
                    )
                    return

            settings["output_dir"] = str(
                new_output
            )
            settings["archive_dir"] = str(
                new_archive
            )
            settings["llm_model"] = (
                new_model
            )
            settings["llm_context_size"] = (
                new_context_size
            )
            settings["m4a_retention_days"] = (
                new_retention_days
            )
            settings[
                "archived_m4a_retention_days"
            ] = new_archived_retention_days

            save_app_settings(settings)
            dialog.accept()

            QMessageBox.information(
                self,
                "Preferences Saved",
                preferences_saved_message(new_archive),
            )

        def update_context_size_visibility():
            is_custom = (
                context_size_combo.currentData()
                == -1
            )
            custom_context_size.setVisible(
                is_custom
            )
            if custom_context_label is not None:
                custom_context_label.setVisible(
                    is_custom
                )

        output_browse.clicked.connect(
            choose_output_folder
        )
        archive_browse.clicked.connect(
            choose_archive_folder
        )
        archive_input.textChanged.connect(
            update_archive_status
        )
        refresh_models_button.clicked.connect(
            refresh_installed_models
        )
        model_combo.currentTextChanged.connect(
            update_model_status
        )
        context_size_combo.currentIndexChanged.connect(
            update_context_size_visibility
        )
        buttons.accepted.connect(
            save_preferences
        )
        buttons.rejected.connect(
            dialog.reject
        )

        update_archive_status()
        refresh_installed_models()
        update_context_size_visibility()
        dialog.exec()

    def _execution_profile_changed(
        self,
        profile_name: str,
    ):
        update_app_setting(
            "execution_profile",
            profile_name,
        )

        if (
            self.query_thread is None
            or not self.query_thread.isRunning()
        ):
            self.query_status_label.setText(
                format_query_ready_status(
                    profile_name
                )
            )

    def _send_query(self):
        if not self.current_context:
            self.context_view.setPlainText(
                "Select a session first."
            )
            return

        user_prompt = (
            self.chat_input
            .toPlainText()
            .strip()
        )

        if not user_prompt:
            return

        self.pending_user_prompt = user_prompt

        conversation_history = []

        if self.current_session:
            conversation_history = (
                self.current_session.get(
                    "conversation_history",
                    [],
                )
            )

        self.send_button.setEnabled(
            False
        )

        self.send_button.setText(
            "Thinking..."
        )

        execution_profile = (
            self.execution_profile_combo.currentText()
        )

        self.query_status_label.setText(
            format_query_working_status(
                execution_profile
            )
        )

        self.query_elapsed_timer.start()
        self.query_elapsed_label.setText(
            "Elapsed: 00:00"
        )
        self.query_elapsed_update_timer.start()

        self.chat_input.setEnabled(
            False
        )

        self.query_thread = QThread()

        self.query_worker = QueryWorker(
            user_prompt,
            self.current_context[
                "merged_memory"
            ],
            conversation_history,
            meeting_memories=(
                self.current_context.get(
                    "meeting_memories"
                )
            ),
            selected_meetings=(
                self.current_context.get(
                    "selected_meetings"
                )
            ),
            topic_filter=(
                self.current_context.get(
                    "topic_filter"
                )
            ),
            execution_profile=(
                execution_profile
            ),
        )

        self.query_worker.moveToThread(
            self.query_thread
        )

        self.query_thread.started.connect(
            self.query_worker.run
        )

        self.query_worker.finished.connect(
            self._query_finished
        )

        self.query_worker.failed.connect(
            self._query_failed
        )

        self.query_worker.finished.connect(
            self.query_thread.quit
        )

        self.query_worker.failed.connect(
            self.query_thread.quit
        )

        self.query_thread.finished.connect(
            self.query_worker.deleteLater
        )

        self.query_thread.finished.connect(
            self.query_thread.deleteLater
        )

        self.query_thread.finished.connect(
            self._query_thread_finished
        )

        self.query_thread.start()

    def _query_finished(
        self,
        response: str,
        execution_metadata: dict,
    ):
        self._stop_query_elapsed()

        execution_profile = (
            self.execution_profile_combo.currentText()
        )
        self.query_status_label.setText(
            format_query_finished_status(
                execution_metadata,
                execution_profile,
            )
        )

        self.query_status_label.setToolTip(
            format_auto_execution_tooltip(
                execution_metadata
            )
        )

        if (
            self.current_session
            and self.current_session.get(
                "session_name"
            )
        ):
            append_query_exchange(
                self.current_session,
                self.current_meeting_dirs,
                user_prompt=self.pending_user_prompt,
                assistant_response=response,
                save_session_func=save_chat_session,
            )

        self.pending_user_prompt = None

        self._render_conversation()

        self.chat_input.clear()

        self._reset_query_ui()

    def _query_failed(
        self,
        error: str,
    ):
        self._stop_query_elapsed()

        execution_profile = (
            self.execution_profile_combo.currentText()
        )

        self.query_status_label.setText(
            format_query_error_status(
                execution_profile
            )
        )

        self.context_view.setPlainText(
            "Query failed:\n\n"
            + error
        )

        self.pending_user_prompt = None

        self._reset_query_ui()

    def _update_query_elapsed(self):
        if not self.query_elapsed_timer.isValid():
            return

        elapsed_ms = (
            self.query_elapsed_timer.elapsed()
        )

        self.query_elapsed_label.setText(
            f"Elapsed: {format_elapsed(elapsed_ms)}"
        )

    def _stop_query_elapsed(self):
        self.query_elapsed_update_timer.stop()

        if not self.query_elapsed_timer.isValid():
            return

        elapsed_ms = (
            self.query_elapsed_timer.elapsed()
        )

        self.query_elapsed_label.setText(
            f"Elapsed: {format_elapsed(elapsed_ms)}"
        )

        self.query_elapsed_timer.invalidate()

    def _reset_query_ui(self):
        self.send_button.setText(
            "Send"
        )

        self.send_button.setEnabled(
            True
        )

        self.chat_input.setEnabled(
            True
        )

    def _query_thread_finished(self):
        self.query_worker = None
        self.query_thread = None

    def closeEvent(self, event):
        if (
            self.transcribe_thread is not None
            and self.transcribe_thread.isRunning()
        ):
            QMessageBox.information(
                self,
                "Transcription Still Running",
                (
                    "The transcription pipeline is still running. "
                    "Please wait for it to finish before quitting "
                    "Meeting Transcriber."
                ),
            )
            event.ignore()
            return

        if (
            self.publish_thread is not None
            and self.publish_thread.isRunning()
        ):
            QMessageBox.information(
                self,
                "Publish Still Running",
                (
                    "Publish & Archive is still running. "
                    "Please wait for it to finish before quitting "
                    "Meeting Transcriber."
                ),
            )
            event.ignore()
            return

        if (
            self.query_thread is not None
            and self.query_thread.isRunning()
        ):
            QMessageBox.information(
                self,
                "Query Still Running",
                (
                    "Qwen is still processing the current query. "
                    "Please wait for it to finish before quitting "
                    "Meeting Transcriber."
                ),
            )
            event.ignore()
            return

        self.query_elapsed_update_timer.stop()

        if self.query_elapsed_timer.isValid():
            self.query_elapsed_timer.invalidate()

        self.transcribe_elapsed_update_timer.stop()

        if self.transcribe_elapsed_timer.isValid():
            self.transcribe_elapsed_timer.invalidate()

        event.accept()


def main():
    app = QApplication(
        sys.argv
    )

    window = (
        MeetingTranscriberWindow()
    )

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
