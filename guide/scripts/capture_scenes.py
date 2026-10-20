"""Public sample data for real guide capture windows; no network AI calls."""
ADDITIONAL_SCENES = (
    "translation-overview", "search-filter", "ai-chat", "ai-settings",
    "conditional-tone", "model-comparison", "glossary-inheritance", "source-diff",
    "thumbnail-edit", "chat-apply", "mcp-settings", "update-status",
)


def prepare(scene, controller, entrance, root):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QPixmap
    from autolingua2.ir.imported import ImportedTranslation, SourceRef
    from autolingua2.ir.project import TranslationProject, TranslationSource
    from autolingua2.ir.unit import TranslationUnit
    from autolingua2.ir.state import UnitState
    from autolingua2.services.projects.workspaces import WorkspaceService
    from autolingua2.ui.dialogs.settings import SettingsDialogController

    settings = None
    keep = []
    units = [TranslationUnit(key, key, original, context="ガイド用サンプル") for key, original in (
        ("menu.start", "Start a new adventure"),
        ("menu.continue", "Continue your journey"),
        ("menu.settings", "Settings"),
        ("dialogue.welcome", "Welcome back, traveler."),
        ("quest.harbor", "Meet the captain at the harbor."),
        ("quest.reward", "Your reward awaits."),
    )]
    adapter = next(iter(entrance.plugins.parsers.values()))
    game = adapter.supported_games[0]
    project = TranslationProject(name="ガイド用サンプル", source_language="en",
        target_language="ja", adapter_id=adapter.id, game_id=game.id,
        source_root=str(root),
        units=units, sources=[TranslationSource("sample", "guide_sample.yml")])
    imported = ImportedTranslation(project, source_refs={
        unit.id: SourceRef("sample", unit.id) for unit in units})
    service = WorkspaceService(imported)
    workspace = service.add("ja")
    for unit, text in zip(units, ("新しい冒険を始める", "旅を続ける", "設定", "", "", "")):
        workspace.records[unit.id].target_text = text
        workspace.records[unit.id].state = UnitState.HUMAN_TRANSLATED if text else UnitState.UNTRANSLATED
    controller.load_import(imported, service)
    controller.window.setWindowTitle("Autolingua Desktop — ガイド用サンプル")
    controller.status_filter.setCurrentIndex(0)
    controller.refresh_all()
    target = controller.window
    target.resize(1440, 900)

    if scene in ("ai-settings", "conditional-tone", "glossary-inheritance", "mcp-settings"):
        settings = SettingsDialogController(entrance)
        category = {"ai-settings": "ai", "conditional-tone": "tone",
                    "glossary-inheritance": "glossary", "mcp-settings": "mcp"}[scene]
        if not settings.select_category(category):
            raise RuntimeError(f"Missing settings category: {category}")
        target = settings.dialog
        target.resize(1250, 850)
        if scene == "ai-settings":
            from autolingua2.services.settings.settings_store import AiModel
            settings.ai_page.model_list.populate([AiModel("モデル名（入力例）", "your-model-id")])
        elif scene == "conditional-tone":
            from autolingua2.ir.tone import ToneItem, ConditionalTone, ToneBlock, ToneBranch, ToneCondition
            page = settings.tone_page
            page.tones = [ToneItem("polite", "案内・説明", "丁寧な、です・ます調で翻訳する。"),
                          ToneItem("dialogue", "登場人物の会話", "自然で親しみやすい会話調で翻訳する。"),
                          ConditionalTone("sample", "キーで口調を切り替える", ToneBlock([
                              ToneBranch(ToneCondition("key", "starts_with", "dialogue."), "dialogue"),
                              ToneBranch(None, "polite")]))]
            page._refresh_choices("sample")
            page.tree.setCurrentItem(page.branches[0][0])
        elif scene == "glossary-inheritance":
            page = settings.glossary_page
            data = page.games.currentData()
            base = page.store.ensure_root(*data)
            child = page.store.add_glossary(base.id, "冒険編の用語集（サンプル）")
            page.store.add_glossary(child.id, "港町の会話（サンプル）")
            page._game_changed(glossary_id=child.id)
            page.tree.expandAll()
    elif scene == "search-filter":
        controller.search.setText("quest.")
        controller.status_filter.setCurrentText("未翻訳")
        controller.refresh_all()
    elif scene in ("ai-chat", "chat-apply"):
        chat = controller.chat_dock
        chat.dock.setFloating(True)
        chat.dock.setVisible(True)
        chat.dock.resize(1050, 850)
        target = chat.dock
        chat._append("user", "【ガイド用サンプル・未送信】harbor の訳語を「港」に統一したいです。")
        if scene == "ai-chat":
            chat._append("assistant", "【表示例・AI実行結果ではありません】\n\nこの文脈では harbor を「港」と訳します。\n\n原文：Meet the captain at the harbor.\n\n訳例：港で船長に会う。")
            chat.input.setPlainText("選択した文章の訳語を確認してください。")
        else:
            chat.history.setZoomFactor(0.7)
            unit = next(unit for unit in service.units(workspace) if unit.id == "quest.harbor")
            doc = controller.operations._record_document(service, workspace, unit)
            controller.operations._edit_units({"project_id": controller.operations.project_id,
                "language": "ja", "changes": [{"id": unit.id,
                "revision": doc["revision"], "translation": "港で船長に会う。"}]}, confirmation=True)
            # Scroll the real viewer to the proposal heading rather than its bottom.
            QTimer.singleShot(2500, lambda: chat.history.page().runJavaScript(
                "document.querySelector('.operation')?.scrollIntoView({block: 'start'});"
                "document.querySelectorAll('.change-list').forEach(el => el.scrollTop = 0);"))
    elif scene == "model-comparison":
        from autolingua2.ui.dialogs.multi_model_dialog import MultiModelTranslationDialog
        # An empty source avoids dispatching AI requests. Cards contain labeled samples.
        target = MultiModelTranslationDialog("", [
            ("sample", "表示例", "sample-a", "モデルA（サンプル）"),
            ("sample", "表示例", "sample-b", "モデルB（サンプル）")],
            controller.provider_registry, {}, "sample-a", controller.ai_client,
            parent=controller.window, default_provider_id="sample")
        target.edit_source.setPlainText("Meet the captain at the harbor.\n（以下は表示例であり、AI実行結果ではありません）")
        for card, text in zip(target._cards.values(), ("港で船長に会う。", "港で船長と落ち合う。")):
            card.set_result(text)
        target.resize(1000, 750)
        keep.append(target)
    elif scene == "source-diff":
        from autolingua2.ir.source_watch import WatchTarget
        from autolingua2.services.translation.source_updates import SourceChange, SourceUpdate
        from autolingua2.ui.dialogs.source_watch import SourceUpdateDialog
        update = SourceUpdate(WatchTarget("", "ガイド用サンプル", "", [".yml"]), "sample", imported, [
            SourceChange("変更", "quest.harbor", "Meet the captain.", "Meet the captain at the harbor."),
            SourceChange("追加", "quest.reward", "", "Your reward awaits."),
            SourceChange("削除", "quest.old", "Return to the old camp.", "")])
        dialog = SourceUpdateDialog(update, controller.window)
        target = dialog.dialog
        target.resize(1100, 780)
        keep.append(dialog)
    elif scene == "thumbnail-edit":
        from autolingua2.ui.dialogs.thumbnail import ThumbnailDialog
        image = QPixmap(str(root / "assets/images/app.png"))
        if image.isNull():
            raise RuntimeError("Sample thumbnail is missing")
        target = ThumbnailDialog(image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation), icon_manager=entrance.icons)
        target.resize(1250, 850)
        target.set_tool("scale")
        QTimer.singleShot(1000, target.view.fit_canvas)
        keep.append(target)
    elif scene == "update-status":
        from autolingua2.ui.dialogs.update import UpdateDialogController
        dialog = UpdateDialogController(controller.window)
        # Demonstrate the real error page without downloading or installing updates.
        dialog._on_check_failed("ガイド用のエラー表示例です。\n更新情報を取得できませんでした。\n接続状況を確認し、「再試行」を押してください。")
        target = dialog.dialog
        target.resize(900, 650)
        keep.append(dialog)
    return target, settings, keep
