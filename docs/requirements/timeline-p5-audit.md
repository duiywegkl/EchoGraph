# P5 reachability and deletion audit

## Roots and request edges

- Desktop: `run_ui.main()` -> `create_app_and_window()` -> local `IntegratedPlayPage`/`TimelineEngine`; Tavern `GraphPage`/`ConfigPage`; backend child `api_server.py`.
- Plugin `index.js` -> EchoGraph: `POST /timeline/heartbeat`, `GET /timeline/identity/{chat_uuid}`, `POST /timeline/register`, `POST /timeline/base`, `POST /timeline/sync`, `GET /timeline/status/{chat_uuid}`, `POST /timeline/retry/{chat_uuid}`, `GET /timeline/prompt/{chat_uuid}`. It also calls SillyTavern `/api/chats/search`.
- Desktop -> backend: `GET /system/liveness`, `POST /system/reload_config`, `GET /system/plugin_status`, `GET /timeline/current`, `GET /timeline/status/{chat_uuid}`, `GET /timeline/graph/{chat_uuid}`, `POST /timeline/retry/{chat_uuid}`, `POST /timeline/manual/{chat_uuid}`, `POST /timeline/undo/{chat_uuid}`, `POST /timeline/redo/{chat_uuid}`.

## Retained backend endpoints

- `GET /system/liveness` -> `liveness`
- `GET /system/plugin_status` -> `get_plugin_status`
- `GET /timeline/current` -> `timeline_current`
- `GET /timeline/graph/{chat_uuid}` -> `timeline_graph`
- `GET /timeline/identity/{chat_uuid}` -> `timeline_identity`
- `GET /timeline/prompt/{chat_uuid}` -> `timeline_prompt`
- `GET /timeline/status/{chat_uuid}` -> `timeline_status`
- `POST /system/reload_config` -> `reload_system_config`
- `POST /timeline/base` -> `timeline_base`
- `POST /timeline/heartbeat` -> `timeline_heartbeat`
- `POST /timeline/manual/{chat_uuid}` -> `timeline_manual`
- `POST /timeline/redo/{chat_uuid}` -> `timeline_redo`
- `POST /timeline/register` -> `timeline_register`
- `POST /timeline/retry/{chat_uuid}` -> `timeline_retry`
- `POST /timeline/sync` -> `timeline_sync`
- `POST /timeline/undo/{chat_uuid}` -> `timeline_undo`

## Reachable source modules and callable definitions

The import closure starts at the two Python entry points. The callable inventory is conservative: it includes methods of instantiated UI classes, Qt slots, and helpers whose branch may not execute on every startup. Package initializers are included because Python imports them.

- `api_server.py`: `reload_system_config`; `liveness`; `timeline_heartbeat`; `get_plugin_status`; `_tavern_timeline_service`; `_timeline_call`; `timeline_register`; `timeline_identity`; `timeline_base`; `timeline_sync`; `timeline_status`; `timeline_retry`; `timeline_graph`; `timeline_manual`; `timeline_undo`; `timeline_redo`; `timeline_prompt`; `timeline_current`
- `run_ui.py`: `local_data_root`; `ChatBubble(__init__, set_delete_mode, mousePressEvent, setup_ui)`; `LoadingBubble(__init__, setup_ui, update_animation, stop_animation)`; `ChatDisplayWidget(__init__, setup_ui, add_message, set_delete_mode, on_message_clicked, show_loading_animation, remove_loading_animation, scroll_to_bottom, clear_messages, remove_last_ai_message, get_last_user_message)`; `GraphBridge(__init__, editNode, refreshGraph, saveLayout, createRelation, createRelationship, updateRelationship, deleteRelationship, updateRelationshipById, deleteRelationshipById, undoManual, redoManual, log)`; `ConversationManager(__init__, load_conversations, create_conversation, delete_conversation, rename_conversation, switch_conversation, get_current_conversation, add_message, _message, add_swipe, switch_swipe, edit_message, branch_from, delete_message_at, clear_current_conversation, _save_conversation)`; `TimelineWorker(__init__, run)`; `IntegratedPlayPage(__init__, load_existing_conversations, init_ui, create_toolbar, create_conversation_management, create_input_area, connect_signals, eventFilter, _restore_local_graph, on_mode_change, enable_chat_interface, _start_tavern_session_polling, _stop_tavern_session_polling, auto_switch_to_local_mode, check_api_connection, update_status_display, create_new_conversation, delete_current_conversation, rename_current_conversation, switch_conversation, update_conversation_combo, load_conversation, _show_local_message, switch_message_swipe, edit_chat_message, branch_chat_message, queue_timeline, _start_timeline, _timeline_complete, _show_effective_graph, _timeline_failed, _timeline_finished, retry_timeline, _sync_engine_hot_memory_from_current_conversation, append_message, show_loading_animation, remove_loading_animation, send_message, process_message, process_test_message, on_grag_data_ready, on_llm_response_ready, on_llm_error, on_llm_worker_finished, regenerate_last_response, toggle_delete_mode, on_chat_message_deleted, clear_conversation)`; `EntityListDelegate(paint)`; `GraphPage(__init__, init_ui, create_graph_panel, create_control_panel, connect_signals, refresh_graph, _selected_filter_type, update_entity_list_with_data, update_stats_with_data, _graph_layout_path, load_graph_layout, save_graph_layout, clear_graph_layout, generate_graph_html_with_data, _get_type_group, update_entity_list, get_all_entities, _tavern_mutation, mutate_relationship, save_entities, _entity_payload, _manual_context, reload_manual_graph, update_manual_controls, undo_manual, redo_manual, update_stats, search_nodes, clear_search, filter_entities, on_entity_selected, focus_on_node, add_node, edit_node, edit_node_with_python_dialog, delete_node, export_graph, reset_view, clear_graph, _api_base_url, _update_mode_controls, enter_tavern_mode, exit_tavern_mode, clear_graph_display, refresh_from_api_server, _refresh_timeline_graph, retry_tavern_timeline, _generate_graph_html_from_api_data, _update_ui_from_api_data, _show_tavern_mode_placeholder)`; `ModelFetchWorker(__init__, run)`; `BackendReloadWorker(__init__, run)`; `ConfigPage(__init__, showEvent, hideEvent, init_ui, connection_status_from_response, refresh_connection_status, _finish_connection_status, load_config, update_model_details, fetch_models, _models_fetched, _models_failed, _models_fetch_finished, _show_save_result, save_config)`; `EchoGraphMainWindow(__init__, apply_theme, init_components, init_managers, check_api_server_running, start_api_server, init_ui, setup_cross_page_connections, on_conversation_changed, load_conversation_knowledge_graph, closeEvent)`; `create_app_and_window`; `main`
- `src/__init__.py`: package marker/imports
- `src/core/__init__.py`: package marker/imports
- `src/core/llm_client.py`: `ChatResult()`; `LLMClient(__init__, chat, chat_with_metadata, generate_response)`
- `src/graph/__init__.py`: package marker/imports
- `src/graph/knowledge_graph.py`: `KnowledgeGraph(__init__, add_or_update_node, add_edge, get_node, get_subgraph_for_context, to_text_representation, search_nodes, save_graph, load_graph, delete_node, delete_edge, resolve_attribute_conflict, add_or_update_node_with_conflict_resolution, get_node_history, mark_node_as_deleted, get_active_nodes, rename_node, cleanup_deleted_nodes, clear)`
- `src/graph/node_types.py`: `NodeType()`; `prompt_types`; `normalize_type`; `normalize_node`; `display_name`
- `src/memory/__init__.py`: package marker/imports
- `src/memory/attention.py`: `EntityImportanceEvaluator(__init__, collective_score, holistic_score, score)`
- `src/memory/basic_memory.py`: `BasicMemory(__init__, add_conversation, get_context, update_state, get_state, save_to_file, load_latest_from_file, _cleanup_old_snapshots)`
- `src/memory/grag_memory.py`: `GRAGMemory(__init__, _load_entities_from_json, sync_entities_to_json, set_entities_json_path, reload_entities_from_json, add_conversation, get_recent_conversation, update_state, get_state, add_or_update_node, add_edge, rename_node, update_edge, delete_node, delete_edge, mark_node_as_deleted, get_active_nodes, cleanup_old_deleted_nodes, get_knowledge_graph_context, _importance_evaluator, _filter_context_subgraph, get_entity_importance_report, get_optimized_character_context, retrieve_context_for_prompt, save_all_memory, clear_all)`
- `src/scenarios/chrono_trigger_scenario.py`: `get_chrono_trigger_scenario`
- `src/timeline/__init__.py`: package marker/imports
- `src/timeline/base.py`: `_clean`; `_entries`; `_books`; `_cards`; `base_hash`; `_entity_id`; `_edge_id`; `lore_messages`; `build_base`; `BaseGraphBuilder(__init__, build_base)`
- `src/timeline/budget.py`: `estimate_tokens`; `plan_groups`
- `src/timeline/engine.py`: `SyncResult()`; `TimelineEngine(__init__, _chat_locks, _keys_at, _sync_locked, sync, invalidate, _validated_ops, _store_segment, process)`
- `src/timeline/extractor.py`: `ExtractionRequestError()`; `ExtractionValidationError()`; `_CheckedClient(__init__, __getattr__)`; `TimelineExtractor(__init__, request_text, _validate, extract)`
- `src/timeline/graph.py`: `GraphError()`; `_identifier`; `_record`; `GraphState(__init__, _validate, copy, to_dict, from_dict, __eq__, apply)`; `Delta(to_dict, from_dict, _apply, apply_forward, apply_reverse)`; `diff`
- `src/timeline/initialization.py`: `world_batches`; `extraction_prompt`
- `src/timeline/local.py`: `example_state`; `normalize_conversation`; `active_content`; `timeline_messages`; `graphml_state`; `state_to_memory`; `register_local`
- `src/timeline/manual.py`: `effective_state`; `ManualLayer(__init__, can_undo, can_redo, _save, apply, undo, redo)`
- `src/timeline/retrieval.py`: `prompt_context`
- `src/timeline/segments.py`: `_hash`; `_content`; `Segment()`; `segment_messages`
- `src/timeline/store.py`: `StoreError()`; `_now`; `Registration()`; `TimelineStore(__init__, _path, _read, _write, put_base, get_base, get_chat, put_chat, register_chat, has_delta, get_delta, put_delta, put_snapshot, state_at)`
- `src/timeline/tavern.py`: `TavernTimeline(__init__, _owner_key, _owner_record, register, base, _bind_base, _build_base, sync, _schedule, _work, retry, status, graph, edit, history, prompt)`
- `src/ui/__init__.py`: package marker/imports
- `src/ui/generators/graph_html_generator.py`: `legend_html`; `GraphHTMLGenerator(__init__, generate_graph_html, _generate_from_template, _generate_builtin_template, _generate_fallback_html)`
- `src/ui/graph_layout_store.py`: `layout_path`; `_valid_positions`; `load_layout`; `save_layout`; `merge_layout`; `clear_layout`
- `src/ui/graph_temp_files.py`: `graph_page_path`; `tavern_placeholder_path`; `_pid_running`; `cleanup_stale_graph_pages`; `cleanup_current_graph_pages`
- `src/ui/managers/__init__.py`: package marker/imports
- `src/ui/managers/resource_cleanup_manager.py`: `ResourceCleanupManager(__init__, cleanup_all_resources, cleanup_llm_threads, cleanup_api_server, save_application_data)`
- `src/ui/managers/window_manager.py`: `WindowManager(setup_window, center_window, apply_theme)`
- `src/ui/theme.py`: `resolve_ui_theme`; `get_theme`; `current`; `current_name`; `needs_switch`; `set_theme`; `node_type_colors`; `css_variables`; `build_app_stylesheet`
- `src/ui/value_unit_input.py`: `UnitSpec()`; `ValueUnitInput(__init__, _factor, _rounded, _base_value, _display, _range_text, _refresh_validation, _text_changed, _change_unit, value, setValue, isValid, errorText)`
- `src/ui/workers/__init__.py`: package marker/imports
- `src/ui/workers/llm_worker.py`: `LLMWorkerThread(__init__, run)`
- `src/utils/__init__.py`: package marker/imports
- `src/utils/config.py`: `_load_file_environment`; `LLMConfig()`; `TimelineConfig()`; `MemoryConfig()`; `GameConfig()`; `SystemConfig()`; `LoggingConfig()`; `Config(__init__, _load_config)`; `reload_config`; `reload_config_if_changed`
- `src/utils/llm_json.py`: `validate_kg`; `validate_operations`; `_json_text`; `_parse`; `request_json`
- `src/utils/model_catalog.py`: `validate_endpoint`; `_first`; `_flag`; `context_size`; `model_details`; `parse_models`; `fetch_models`

## Removed endpoints

Every route below has no caller in the current plugin or desktop. The timeline API and desktop status routes above cover their live functions.

- `DELETE /sessions/{session_id}/nodes/{node_name}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `DELETE /sessions/{session_id}/relationships` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `DELETE /tavern/character/{character_name}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /characters/{character_name}/exists` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /health` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /initialize_status/{task_id}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /sessions` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /sessions/{session_id}/export` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /sessions/{session_id}/graph_status` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /sessions/{session_id}/stats` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /system/quick_reset` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /system/tavern_mode` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /tavern/available_characters` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /tavern/characters` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /tavern/current_session` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /tavern/get_character/{character_id}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `GET /tavern/sessions` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /enhance_prompt` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /frontend/refresh_graph` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /initialize` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /initialize_async` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /process_conversation` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/clear` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/nodes` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/reinitialize` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/relationships` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/reset` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sessions/{session_id}/save` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /sync_conversation` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /system/full_reset` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /system/tavern_mode` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/cleanup_orphaned_sessions` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/new_session` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/process_message` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/sessions/{session_id}/reinitialize_from_plugin` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/sessions/{session_id}/request_reinitialize` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /tavern/submit_character` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `POST /update_memory` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `PUT /sessions/{session_id}/nodes/{old_node_name}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `PUT /sessions/{session_id}/relationships` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.
- `WEBSOCKET /ws/tavern/{session_id}` ? retired session, initialization, graph mutation, or health/reset contract; no current request edge.

## Deleted files

Each file below was unreachable from the live entry points after removing the retired routes and UI branches.

- `MIGRATION_GUIDE.md` ? Only documented removed mechanisms or architecture.
- `REFACTORING_PLAN.md` ? Only documented removed mechanisms or architecture.
- `REFACTOR_SUMMARY.md` ? Only documented removed mechanisms or architecture.
- `docs/sliding_window_design.md` ? Only documented removed mechanisms or architecture.
- `examples/memory_system_demo.py` ? Only demonstrated the removed GameEngine flow.
- `src/agents/__init__.py` ? No live entry-point import remains.
- `src/api/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/main.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/middleware/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/middleware/security.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/models/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/models/requests.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/models/responses.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/graph.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/memory.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/sessions.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/system.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/routes/tavern.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/services/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/services/memory_service.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/services/session_service.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/websocket/__init__.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/websocket/handlers.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/api/websocket/manager.py` ? Unused parallel FastAPI package; the live backend is api_server.py.
- `src/core/conflict_resolver.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/delayed_update.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/game_engine.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/grag_update_agent.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/perception.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/rpg_text_processor.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/sliding_window.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/text_processor.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/core/validation.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/graph/graph_operations.py` ? Only the retired local graph mutation path and its tests imported it.
- `src/storage/__init__.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/storage/tavern_storage_manager.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/tavern/__init__.py` ? Only the retired per-turn or per-character session flow imported it.
- `src/ui/components/__init__.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/components/base.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/components/chat_interface.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/components/config_panel.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/components/graph_bridge.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/components/status_monitor.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/dialogs/__init__.py` ? No live entry-point import remains.
- `src/ui/managers/conversation_manager.py` ? No live desktop import remains.
- `src/ui/managers/scenario_manager.py` ? No live desktop import remains.
- `src/ui/pages/__init__.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/pages/config_page.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/pages/graph_page.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/pages/integrated_play_page.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/widgets/__init__.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/widgets/chat_components.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/windows/__init__.py` ? Not imported by the run_ui.py desktop entry point.
- `src/ui/windows/main_window.py` ? Not imported by the run_ui.py desktop entry point.
- `src/utils/enhanced_config.py` ? Only the retired parallel API/configuration flow imported it.
- `src/utils/exceptions.py` ? Only the retired parallel API/configuration flow imported it.
- `src/utils/security.py` ? Only the retired parallel API/configuration flow imported it.
- `tests/graph_layout_harness.py` ? Only exercised removed code or read retired real-data fixtures.
- `tests/run_ui_tavern_startup_harness.py` ? Only exercised removed code or read retired real-data fixtures.
- `tests/test_graph_operations.py` ? Only exercised removed code or read retired real-data fixtures.
- `tests/test_manual_graph_edit.py` ? Only exercised removed code or read retired real-data fixtures.
- `tests/test_tavern_initialization_recovery.py` ? Only exercised removed code or read retired real-data fixtures.
- `tests/test_websocket_endpoint.py` ? Only exercised removed code or read retired real-data fixtures.

## Root document disposition

- `MIGRATION_GUIDE.md`: stale, deleted; it described the removed parallel API architecture.
- `REFACTORING_PLAN.md`: stale, deleted; its target modules and WebSocket service were removed.
- `REFACTOR_SUMMARY.md`: stale, deleted; its architecture and metrics applied to removed code.
- `docs/TODO_AUDIT.md`: partially stale, retained and rewritten for current timeline work.

## Section 9.3 disposition

- The old synchronization field mismatch is eliminated with the removed endpoint.
- The delayed update durability issue is eliminated with the removed queue; timeline extraction persists before advancing the head.
- The short timeout duplicate processing risk is eliminated with the removed per-turn endpoint; the plugin sends the full visible timeline and polls status.

## Removed tests

Each test below asserted a retired endpoint or implementation. The live memory adapter persistence check was moved to `tests/test_memory_adapter.py`.

- `tests/test_graph_layout_store.py::test_tavern_layout_is_per_character_session_and_clear` ? retired API or implementation.
- `tests/test_graph_operations.py::test_rename_preserves_edges_and_persists_both_files` ? retired API or implementation.
- `tests/test_graph_operations.py::test_delete_removes_node_and_incident_edges_from_both_files` ? retired API or implementation.
- `tests/test_graph_operations.py::test_duplicate_name_rejected_before_writing` ? retired API or implementation.
- `tests/test_graph_operations.py::test_clear_keeps_non_graph_memory_and_clears_both_files` ? retired API or implementation.
- `tests/test_graph_operations.py::test_edit_removes_deleted_dynamic_attributes` ? retired API or implementation.
- `tests/test_graph_operations.py::test_real_graph_save_surfaces_serialization_failure` ? retired API or implementation.
- `tests/test_llm_json_initialization.py::test_chunked_world_book_merges_and_bounds_prompts` ? retired API or implementation.
- `tests/test_llm_json_initialization.py::test_one_batch_failure_is_partial` ? retired API or implementation.
- `tests/test_llm_json_initialization.py::test_all_batches_fail_without_persisting_fallback` ? retired API or implementation.
- `tests/test_llm_json_initialization.py::test_openai_initialization_all_batches_have_no_output_cap` ? retired API or implementation.
- `tests/test_llm_json_initialization.py::test_openai_continuation_repair_and_grag_update_have_no_output_cap` ? retired API or implementation.
- `tests/test_manual_graph_edit.py::test_local_relationship_path` ? retired API or implementation.
- `tests/test_manual_graph_edit.py::test_api_mutations_and_broadcast` ? retired API or implementation.
- `tests/test_manual_graph_edit.py::test_broadcast_failure_does_not_fail_mutation` ? retired API or implementation.
- `tests/test_manual_graph_edit.py::test_failed_rename_returns_500_without_update_or_broadcast` ? retired API or implementation.
- `tests/test_model_config_reload.py::test_backend_reload_then_retry_initialize` ? retired API or implementation.
- `tests/test_model_config_reload.py::test_agent_build_reloads_changed_env_without_notification` ? retired API or implementation.
- `tests/test_node_types.py::test_prompt_contains_all_types` ? retired API or implementation.
- `tests/test_node_types.py::test_api_create_type_validation` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_leftover_empty_session_plugin_flow_extracts` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_nonempty_session_skips_extraction` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_failed_initialization_is_retryable` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_empty_completed_extraction_does_not_loop` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_autoload_notifies_every_socket` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_partial_failure_rolls_back_nodes_and_retries` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_interrupted_initialization_is_retryable` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_engine_creation_failure_after_registration_is_retryable` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_websocket_failure_contains_backend_reason` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_concurrent_initialize_shares_result` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_failed_initialization_restores_disk` ? retired API or implementation.
- `tests/test_tavern_initialization_recovery.py::test_partial_status_and_reason_visible` ? retired API or implementation.
- `tests/test_websocket_connections.py::test_multiple_tabs_receive_session_broadcast` ? retired API or implementation.
- `tests/test_websocket_connections.py::test_process_conversation_retries_are_idempotent` ? retired API or implementation.
- `tests/test_websocket_endpoint.py::test_websocket_ping_with_existing_character_data` ? retired API or implementation.
