# Complete user journey coverage checklist

This is the implementation work list, starting with ordinary UI actions. **Written does not mean passed or fully covered.** The execution report separately records what actually ran and which states it verified. Every missing entry below remains work to do; component-test acceptance labels do not close it.

## Order of work

1. Basic inputs, keyboard controls, drafts, attachments, history, model test buttons and non-destructive settings choices.
2. Conversation branching/rewinding, context controls, shortcuts, appearance, privacy, memory and local file permissions.
3. Add-on installation/use/removal, MCP, agent tasks, workspace review/apply/reject, failures and recovery.
4. Live account sign-in and provider protocols, physical desktop/voice, installed-release lifecycle and OS-specific behavior. Write these journeys too; execute them only in an appropriate, provisioned environment.

Registered journeys: **138**. Inventory entries: **472**. Entries with at least one specifically mapped path: **144**. A mapped path is not proof of every variant of that capability.

## 1. Launch, setup, and desktop shell

| Capability | User journey implementation |
|---|---|
| F001: Launch the packaged OpenWand app. | Written path: [Launch the app and open Settings from its tray (lines 168-175)](C:/OpenWand/scripts/user_journeys/scenarios.py:168) |
| F002: Launch OpenWand from the source checkout and development launchers. | Written path: [Launch the app and open Settings from its tray (lines 168-175)](C:/OpenWand/scripts/user_journeys/scenarios.py:168) |
| F003: Prevent a second OpenWand instance from running at the same time. | **TODO: write the user journey** |
| F004: Run first-start setup and dependency checks. | Written path: [Fresh first launch opens the setup wizard (lines 113-117)](C:/OpenWand/scripts/user_journeys/scenarios.py:113) |
| F005: Show the guided profile/setup wizard again from Settings. | Written path: [Reopen guided setup from Settings and cancel without changing the provider (lines 556-572)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:556); [Keep unsaved Settings when guided setup asks to save first (lines 575-590)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:575) |
| F006: Move backward and forward through setup steps. | Written path: [Choose language, theme and advanced setup (lines 120-136)](C:/OpenWand/scripts/user_journeys/scenarios.py:120) |
| F007: Choose the app display language during setup. | Written path: [Choose language, theme and advanced setup (lines 120-136)](C:/OpenWand/scripts/user_journeys/scenarios.py:120) |
| F008: Choose the assistant reply language during setup. | Written path: [Choose language, theme and advanced setup (lines 120-136)](C:/OpenWand/scripts/user_journeys/scenarios.py:120) |
| F009: Choose System, Light, or Dark appearance during setup. | Written path: [Choose language, theme and advanced setup (lines 120-136)](C:/OpenWand/scripts/user_journeys/scenarios.py:120) |
| F010: Choose an AI provider, model, endpoint, and API key during setup. | Written path: [Configure a provider and finish first-run setup (lines 139-156)](C:/OpenWand/scripts/user_journeys/scenarios.py:139); [Send the first prompt with the provider chosen during setup (lines 159-165)](C:/OpenWand/scripts/user_journeys/scenarios.py:159) |
| F011: Sign in with a ChatGPT Plus/Pro account during setup. | **TODO: write the user journey** |
| F012: Choose no TTS, local TTS, or cloud TTS during setup. | Written path: [Configure a provider and finish first-run setup (lines 139-156)](C:/OpenWand/scripts/user_journeys/scenarios.py:139) |
| F013: Choose no STT, local Whisper, or cloud/live voice during setup. | Written path: [Configure a provider and finish first-run setup (lines 139-156)](C:/OpenWand/scripts/user_journeys/scenarios.py:139) |
| F014: Open a new chat automatically when setup finishes. | Written path: [Configure a provider and finish first-run setup (lines 139-156)](C:/OpenWand/scripts/user_journeys/scenarios.py:139) |
| F015: Show first-use guidance for trying the main shortcut. | **TODO: write the user journey** |
| F016: Start the UI, brain/model, audio, and platform workers. | **TODO: write the user journey** |
| F017: Display a floating always-on-top OpenWand icon. | Written path: [Click the floating icon, type a custom prompt and receive its answer (lines 586-600)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:586) |
| F018: Show idle, listening, thinking, and speaking icon states. | **TODO: write the user journey** |
| F019: Drag the floating icon to another screen position. | **TODO: write the user journey** |
| F020: Auto-hide the icon when OpenWand is inactive. | **TODO: write the user journey** |
| F021: Show or hide the icon from the tray menu. | **TODO: write the user journey** |
| F022: Open the most recent chat from the tray menu. | **TODO: write the user journey** |
| F023: Open Memory from the tray menu. | Written path: [Open Memory and Addon Manager from the running app (lines 343-351)](C:/OpenWand/scripts/user_journeys/scenarios.py:343) |
| F024: Open the Addon Manager from the tray menu. | Written path: [Open Memory and Addon Manager from the running app (lines 343-351)](C:/OpenWand/scripts/user_journeys/scenarios.py:343) |
| F025: Open Settings from the tray menu. | Written path: [Launch the app and open Settings from its tray (lines 168-175)](C:/OpenWand/scripts/user_journeys/scenarios.py:168); [Keep an unsent draft while opening and closing Settings (lines 159-171)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:159) |
| F026: Open ChatGPT or Claude controls from the provider badge. | **TODO: write the user journey** |
| F027: Open runtime status where the platform worker host supports it. | **TODO: write the user journey** |
| F028: Quit OpenWand from the tray menu. | **TODO: write the user journey** |
| F029: Start OpenWand automatically when the user signs in. | **TODO: write the user journey** |
| F030: Shut workers down cleanly when OpenWand exits. | **TODO: write the user journey** |
## 2. Main ask, explain, fix, and rewrite actions

| Capability | User journey implementation |
|---|---|
| F031: Capture the text currently selected in another application. | **TODO: write the user journey** |
| F032: Open the general intent picker over the current application. | Written path: [Click the floating icon, type a custom prompt and receive its answer (lines 586-600)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:586) |
| F033: Run the built-in **What is this?** action. | Written path: [Click the built-in What is this action and receive its actual prompt (lines 614-623)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:614) |
| F034: Run the built-in **Explain simply** action. | Written path: [Choose Explain simply using its single-key intent shortcut (lines 626-635)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:626) |
| F035: Run the built-in **How do I fix this?** action. | **TODO: write the user journey** |
| F036: Open the rewrite/paste intent picker. | **TODO: write the user journey** |
| F037: Run the built-in **Fix grammar** action. | **TODO: write the user journey** |
| F038: Run the built-in **Simplify** action. | **TODO: write the user journey** |
| F039: Run the built-in **Improve tone** action. | **TODO: write the user journey** |
| F040: Type and submit a custom prompt from the intent picker. | Written path: [Click the floating icon, type a custom prompt and receive its answer (lines 586-600)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:586) |
| F041: Choose an action with its assigned single-key shortcut. | Written path: [Choose Explain simply using its single-key intent shortcut (lines 626-635)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:626) |
| F042: Choose an action by clicking it. | Written path: [Click the built-in What is this action and receive its actual prompt (lines 614-623)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:614) |
| F043: Cancel an intent with Escape. | Written path: [Set intent timeout to zero and keep the picker open until Escape (lines 483-503)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:483); [Cancel the floating intent picker with Escape without sending a request (lines 603-611)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:603) |
| F044: Automatically close an abandoned intent picker after its configured timeout. | Written path: [Save a short intent timeout and let an abandoned picker close (lines 463-480)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:463) |
| F045: Keep the intent picker open until a choice is made by setting timeout to zero. | Written path: [Set intent timeout to zero and keep the picker open until Escape (lines 483-503)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:483) |
| F046: Paste a rewrite result back into the application that originally had focus. | **TODO: write the user journey** |
| F047: Keep an answer in OpenWand without pasting it back. | Written path: [Click the floating icon, type a custom prompt and receive its answer (lines 586-600)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:586) |
| F048: Run localized built-in intent labels and prompts for supported assistant languages. | **TODO: write the user journey** |
| F049: Stream the model response instead of waiting for the entire answer. | Written path: [Verify answer text was visible before the floating request finished (lines 468-487)](C:/OpenWand/scripts/user_journeys/scenarios.py:468) |
| F050: Route a request through the selected primary model and configured fallbacks. | **TODO: write the user journey** |
| F051: Show a useful error/recovery recommendation when a request fails. | Written path: [Show a provider error and return to usable controls (lines 272-282)](C:/OpenWand/scripts/user_journeys/scenarios.py:272); [Send successfully after a failed provider request (lines 285-289)](C:/OpenWand/scripts/user_journeys/scenarios.py:285); [Replace a connection key, show authentication failure and recover (lines 650-670)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:650) |
| F052: Cancel an in-progress request. | Written path: [Cancel streaming and send another prompt (lines 292-302)](C:/OpenWand/scripts/user_journeys/scenarios.py:292) |
## 3. Shortcut management

| Capability | User journey implementation |
|---|---|
| F053: Use the default general picker shortcut: `Ctrl+Q` on Windows or `Ctrl+Alt+Space` on macOS/Linux. | **TODO: write the user journey** |
| F054: Use the default rewrite picker shortcut: `Ctrl+Shift+Q` on Windows or `Ctrl+Alt+Shift+Space` on macOS/Linux. | **TODO: write the user journey** |
| F055: Use the default screen snip shortcut: `Ctrl+Alt+Q`. | **TODO: write the user journey** |
| F056: Use the default add-selection-to-context shortcut: `Alt+Q`. | **TODO: write the user journey** |
| F057: Use the default clear-context shortcut: `Alt+W`. | **TODO: write the user journey** |
| F058: Use the default read-selection-aloud shortcut: `F7`. | **TODO: write the user journey** |
| F059: Hold the default voice-query shortcut `F9`, speak, and release to ask. | **TODO: write the user journey** |
| F060: Toggle live voice with `Shift+F9`. | **TODO: write the user journey** |
| F061: Hold the default dictation shortcut `F8`, speak, and release to paste. | **TODO: write the user journey** |
| F062: Search the shortcut list by action name or description. | Written path: [Search shortcuts, show no matches and restore the complete list (lines 423-436)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:423) |
| F063: Enable or disable each shortcut independently. | **TODO: write the user journey** |
| F064: Click a shortcut field and record a replacement key combination. | **TODO: write the user journey** |
| F065: Clear or cancel a shortcut assignment. | **TODO: write the user journey** |
| F066: Assign two alternate shortcuts to the same action. | **TODO: write the user journey** |
| F067: Detect and warn about conflicting shortcuts. | **TODO: write the user journey** |
| F068: Add a new intent shortcut/caller. | **TODO: write the user journey** |
| F069: Rename an intent shortcut. | **TODO: write the user journey** |
| F070: Remove an intent shortcut. | **TODO: write the user journey** |
| F071: Customize an intent shortcut's action choices. | **TODO: write the user journey** |
| F072: Add an action choice with its own key, label, and model prompt. | **TODO: write the user journey** |
| F073: Remove an action choice. | **TODO: write the user journey** |
| F074: Change an action choice's key, label, or model prompt. | **TODO: write the user journey** |
| F075: Configure the custom-prompt action and its key. | **TODO: write the user journey** |
| F076: Enable or disable paste-back for an intent shortcut. | **TODO: write the user journey** |
| F077: Configure context sources separately for every intent shortcut. | **TODO: write the user journey** |
| F078: Configure allowed model tools separately for every intent shortcut. | **TODO: write the user journey** |
| F079: Configure context and allowed tools for voice queries. | **TODO: write the user journey** |
| F080: Configure context and allowed tools for screen-snip queries. | **TODO: write the user journey** |
| F081: Set dictation to raw transcript or LLM-cleaned transcript. | **TODO: write the user journey** |
## 4. Context collection and capture

| Capability | User journey implementation |
|---|---|
| F082: Add selected text to a persistent context buffer. | **TODO: write the user journey** |
| F083: Clear every item from the context buffer. | **TODO: write the user journey** |
| F084: Remove one context item without clearing the rest. | **TODO: write the user journey** |
| F085: Re-enable a context source that was removed or turned off. | **TODO: write the user journey** |
| F086: Paste clipboard items into the intent overlay as context. | **TODO: write the user journey** |
| F087: Drop files or images onto OpenWand as context. | **TODO: write the user journey** |
| F088: Preview enabled context before sending. | **TODO: write the user journey** |
| F089: Show context-source state and token estimates where available. | **TODO: write the user journey** |
| F090: Toggle context sources with the numbered overlay keys. | **TODO: write the user journey** |
| F091: Include nearby application/window/focused-control context. | Written path: [Change App context per conversation and inspect the actual request (lines 540-553)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:540) |
| F092: Include supported open-document content. | **TODO: write the user journey** |
| F093: Include current clipboard text. | Written path: [Turn clipboard context Off and On and verify what reaches the provider (lines 506-522)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:506) |
| F094: Include current selected text. | Written path: [Disable selected-text context and compare with a new chat's default (lines 525-537)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:525) |
| F095: Include the current browser page. | **TODO: write the user journey** |
| F096: Search the web when the model needs current information. | **TODO: write the user journey** |
| F097: Retrieve a specific website/page for the model. | **TODO: write the user journey** |
| F098: Include local Git status and diff. | **TODO: write the user journey** |
| F099: Fetch GitHub repository metadata. | **TODO: write the user journey** |
| F100: Fetch a GitHub issue or pull request by number. | **TODO: write the user journey** |
| F101: Retrieve relevant long-term memory. | **TODO: write the user journey** |
| F102: Capture a screenshot immediately with the prompt. | **TODO: write the user journey** |
| F103: Let the model request a screenshot only when needed. | **TODO: write the user journey** |
| F104: Let the model request open documents only when needed. | **TODO: write the user journey** |
| F105: Let the model request browser/web context only when needed. | **TODO: write the user journey** |
| F106: Let the model request Git/GitHub context only when needed. | **TODO: write the user journey** |
| F107: Let the model search memory only when needed. | **TODO: write the user journey** |
| F108: Disable each context source for a particular shortcut or conversation. | **TODO: write the user journey** |
| F109: Set local file access to Off. | Written path: [Files Off withholds local file tools from the actual provider (lines 382-391)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:382) |
| F110: Set local file access to Read only. | Written path: [Read-only Files reads a document and withholds writing tools (lines 394-405)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:394) |
| F111: Set local file access to Ask before writing. | Written path: [Preview a file change, approve it and verify the actual file (lines 408-422)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:408) |
| F112: Set local file access to Write automatically. | Written path: [Create and overwrite scoped files with automatic permission (lines 438-450)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:438) |
| F113: Limit file access to configured root folders. | Written path: [Add an allowed file root through the real folder chooser (lines 362-379)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:362); [Reject file access outside the allowed root and to blocked files (lines 453-467)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:453) |
| F114: Block private files with configurable glob patterns. | Written path: [Reject file access outside the allowed root and to blocked files (lines 453-467)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:453) |
| F115: Limit browser, ambient-document, and tool-document context sizes. | **TODO: write the user journey** |
## 5. Screen snipping and vision

| Capability | User journey implementation |
|---|---|
| F116: Open the full-screen snip overlay. | **TODO: write the user journey** |
| F117: Draw a rectangular screen region and attach it. | **TODO: write the user journey** |
| F118: Capture the full screen. | **TODO: write the user journey** |
| F119: Capture the current application/window bounds. | **TODO: write the user journey** |
| F120: Switch between Area, App, and Full capture modes. | **TODO: write the user journey** |
| F121: Cancel capture with Escape. | **TODO: write the user journey** |
| F122: Attach the resulting image to the intent picker. | **TODO: write the user journey** |
| F123: Ask a vision-capable model about the captured image. | **TODO: write the user journey** |
| F124: Route images through the configured Image model and its fallbacks. | **TODO: write the user journey** |
| F125: Show an image returned by a model in the reply bubble or chat. | **TODO: write the user journey** |
## 6. Floating reply bubble

| Capability | User journey implementation |
|---|---|
| F126: Show listening, transcript, progress, answer, warning, and error text beside the icon. | **TODO: write the user journey** |
| F127: Stream answer text into the bubble. | **TODO: write the user journey** |
| F128: Reveal words progressively. | **TODO: write the user journey** |
| F129: Highlight the currently spoken word when timestamps are available. | **TODO: write the user journey** |
| F130: Use normal timed reveal when the TTS provider has no word timestamps. | **TODO: write the user journey** |
| F131: Hold the fast-forward control to speed text and speech. | **TODO: write the user journey** |
| F132: Stop/cancel the current reply from the close/stop control. | **TODO: write the user journey** |
| F133: Dismiss a non-cancellable informational notice. | **TODO: write the user journey** |
| F134: Click the bubble to open the full chat. | Written path: [Click the floating answer to open its conversation and follow up (lines 638-647)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:638) |
| F135: Drag the bubble/icon group. | **TODO: write the user journey** |
| F136: Pause auto-hide while the user hovers or interacts. | **TODO: write the user journey** |
| F137: Wheel-scroll long bubble text. | **TODO: write the user journey** |
| F138: Snap manual scrolling back to the spoken/highlighted line. | **TODO: write the user journey** |
| F139: Select text inside the bubble. | **TODO: write the user journey** |
| F140: Copy selected bubble text. | **TODO: write the user journey** |
| F141: Copy the full bubble text. | **TODO: write the user journey** |
| F142: Display assistant-created images. | **TODO: write the user journey** |
| F143: Edit or delete UI Lab labels from selected bubble text when that add-on is available. | **TODO: write the user journey** |
## 7. Full chat and projects

| Capability | User journey implementation |
|---|---|
| F144: Open persistent multi-turn chat. | Written path: [Send the first prompt with the provider chosen during setup (lines 159-165)](C:/OpenWand/scripts/user_journeys/scenarios.py:159); [Prompt using the provider added in Settings (lines 216-227)](C:/OpenWand/scripts/user_journeys/scenarios.py:216); [Close Chat and reopen the retained conversation (lines 238-243)](C:/OpenWand/scripts/user_journeys/scenarios.py:238); [Reopen the saved provider before the basic user journeys (lines 71-88)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:71); [Type a prompt and send it with Enter (lines 124-131)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:124); [Send Unicode text entered through the user's input method (lines 149-156)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:149); [Keep an unsent draft while opening and closing Settings (lines 159-171)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:159); [Finish the basic journeys with a saved, usable conversation (lines 636-640)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:636); [Finish addon journeys with contributed hooks disabled (lines 312-322)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:312); [Continue ordinary Chat after completing and cancelling agent tasks (lines 217-223)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:217); [Stop the workspace service, disable its addon and return to Chat (lines 160-178)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:160); [Complete the extended stories and retain their last conversation (lines 673-680)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:673); [After a full app restart, reopen saved provider and conversation (lines 455-465)](C:/OpenWand/scripts/user_journeys/scenarios.py:455) |
| F145: Start a new chat from the button or `Ctrl+N`. | Written path: [Start a new conversation with the platform's New shortcut (lines 246-257)](C:/OpenWand/scripts/user_journeys/scenarios.py:246); [Start a new chat with the visible button and retain the old chat (lines 113-121)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:113) |
| F146: Send with Enter and insert a newline with Shift+Enter. | Written path: [Prompt using the provider added in Settings (lines 216-227)](C:/OpenWand/scripts/user_journeys/scenarios.py:216); [Switch Enter behaviour and send a multiline prompt (lines 370-391)](C:/OpenWand/scripts/user_journeys/scenarios.py:370); [Press Enter in an empty chat without sending anything (lines 91-98)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:91); [Submit whitespace without creating a message or network request (lines 101-110)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:101); [Type a prompt and send it with Enter (lines 124-131)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:124); [Insert a newline with Shift+Enter before sending the full draft (lines 134-146)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:134); [Send Unicode text entered through the user's input method (lines 149-156)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:149) |
| F147: Stream assistant text, reasoning summaries, tool activity, and images. | **TODO: write the user journey** |
| F148: Continue a prior conversation. | Written path: [Follow up with prior conversation context (lines 230-235)](C:/OpenWand/scripts/user_journeys/scenarios.py:230); [Close Chat and reopen the retained conversation (lines 238-243)](C:/OpenWand/scripts/user_journeys/scenarios.py:238); [Send successfully after a failed provider request (lines 285-289)](C:/OpenWand/scripts/user_journeys/scenarios.py:285); [Switch between two saved chats and follow up in the selected one (lines 243-258)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:243); [Branch an earlier message and preserve the original conversation (lines 312-331)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:312); [Confirm rewind and follow up without the removed conversation turns (lines 344-356)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:344); [Finish the basic journeys with a saved, usable conversation (lines 636-640)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:636); [Click the floating answer to open its conversation and follow up (lines 638-647)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:638); [Complete the extended stories and retain their last conversation (lines 673-680)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:673); [After a full app restart, reopen saved provider and conversation (lines 455-465)](C:/OpenWand/scripts/user_journeys/scenarios.py:455) |
| F149: Choose whether an overlay request starts a new chat or continues an existing chat. | **TODO: write the user journey** |
| F150: Switch conversations from history. | Written path: [Search conversation history without discarding it (lines 394-407)](C:/OpenWand/scripts/user_journeys/scenarios.py:394); [Start a new chat with the visible button and retain the old chat (lines 113-121)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:113); [Switch between two saved chats and follow up in the selected one (lines 243-258)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:243) |
| F151: Group conversation history by project. | **TODO: write the user journey** |
| F152: Create a project. | Written path: [Cancel creating a project without changing the selected project (lines 359-367)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:359); [Create a project, move a conversation and start a scoped chat (lines 198-213)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:198) |
| F153: Choose the project for new chats. | Written path: [Cancel creating a project without changing the selected project (lines 359-367)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:359); [Create a project, move a conversation and start a scoped chat (lines 198-213)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:198) |
| F154: Scope memory to the selected project. | **TODO: write the user journey** |
| F155: Add a conversation to a project. | Written path: [Create a project, move a conversation and start a scoped chat (lines 198-213)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:198) |
| F156: Pin or unpin a conversation. | Written path: [Rename, pin and unpin a conversation through its history menu (lines 182-195)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:182) |
| F157: Rename a conversation. | Written path: [Rename, pin and unpin a conversation through its history menu (lines 182-195)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:182) |
| F158: Delete a conversation after confirmation. | Written path: [Decline conversation deletion, then confirm deletion (lines 216-228)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:216) |
| F159: Browse files associated with a conversation. | **TODO: write the user journey** |
| F160: Show conversation and message timestamps. | **TODO: write the user journey** |
| F161: Attach one or more files or images with the file picker. | Written path: [Cancel the attachment chooser and keep the draft intact (lines 174-187)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:174); [Choose a file with the real file picker and ask about it (lines 347-359)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:347) |
| F162: Drag and drop files/images into chat. | Written path: [Drop a text file, prompt about it and receive its content (lines 260-269)](C:/OpenWand/scripts/user_journeys/scenarios.py:260); [Remove a pending attachment before sending the prompt (lines 190-204)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:190); [Attach two files together and send both contents (lines 207-221)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:207); [Drop an image, preview its thumbnail and send it to the image route (lines 224-240)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:224) |
| F163: Show pending attachment names and context. | Written path: [Drop a text file, prompt about it and receive its content (lines 260-269)](C:/OpenWand/scripts/user_journeys/scenarios.py:260); [Cancel the attachment chooser and keep the draft intact (lines 174-187)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:174); [Remove a pending attachment before sending the prompt (lines 190-204)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:190); [Attach two files together and send both contents (lines 207-221)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:207) |
| F164: Display attached and returned image thumbnails. | Written path: [Drop an image, preview its thumbnail and send it to the image route (lines 224-240)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:224) |
| F165: Configure App context per conversation. | Written path: [Change App context per conversation and inspect the actual request (lines 540-553)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:540) |
| F166: Configure Browser/Web context per conversation. | Written path: [Change browser context access and verify the actual model request (lines 435-452)](C:/OpenWand/scripts/user_journeys/scenarios.py:435) |
| F167: Configure Selection context per conversation. | Written path: [Disable selected-text context and compare with a new chat's default (lines 525-537)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:525) |
| F168: Configure Clipboard context per conversation. | Written path: [Turn clipboard context Off and On and verify what reaches the provider (lines 506-522)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:506) |
| F169: Configure Screenshot context per conversation. | **TODO: write the user journey** |
| F170: Configure Git/GitHub context per conversation. | **TODO: write the user journey** |
| F171: Configure Memory context per conversation. | **TODO: write the user journey** |
| F172: Configure Files access per conversation. | Written path: [Files Off withholds local file tools from the actual provider (lines 382-391)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:382) |
| F173: Capture selection or screenshot interactively when enabling its chat context chip. | **TODO: write the user journey** |
| F174: Preview context token estimates before sending. | **TODO: write the user journey** |
| F175: Copy selected text from a message. | **TODO: write the user journey** |
| F176: Branch a new conversation from any retained message. | Written path: [Branch an earlier message and preserve the original conversation (lines 312-331)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:312) |
| F177: Rewind the current conversation to any retained message. | Written path: [Cancel rewinding a chat and retain every message (lines 334-341)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:334); [Confirm rewind and follow up without the removed conversation turns (lines 344-356)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:344) |
| F178: Edit or delete UI Lab labels from selected chat text when that add-on is available. | **TODO: write the user journey** |
| F179: Zoom chat text with the supported keyboard/wheel controls. | Written path: [Zoom chat text in, out and back to the default size (lines 295-309)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:295) |
| F180: Show model tool-loop trace when enabled. | **TODO: write the user journey** |
| F181: Split longer answers into planned chunks when enabled. | **TODO: write the user journey** |
| F182: Set the number of planned chunks and the minimum prompt length. | **TODO: write the user journey** |
| F183: Set chat reasoning effort. | **TODO: write the user journey** |
| F184: Auto-elaborate the latest short answer when opening chat. | **TODO: write the user journey** |
| F185: Customize the auto-elaboration prompt. | **TODO: write the user journey** |
## 8. External ChatGPT and Claude conversations

| Capability | User journey implementation |
|---|---|
| F186: Pull local ChatGPT/Codex and Claude Code transcripts into OpenWand. | **TODO: write the user journey** |
| F187: Report imported, updated, and unchanged transcript counts. | **TODO: write the user journey** |
| F188: Keep OpenWand, ChatGPT, and Claude conversation namespaces distinct. | **TODO: write the user journey** |
| F189: Continue a conversation using OpenWand's own model engine. | **TODO: write the user journey** |
| F190: Continue a conversation using the selected ChatGPT/Codex or Claude agent. | **TODO: write the user journey** |
| F191: Choose whether continued messages belong to OpenWand or the selected agent. | **TODO: write the user journey** |
| F192: Push new OpenWand turns back into their source transcript after confirmation. | **TODO: write the user journey** |
| F193: Create a backup before editing an external transcript. | **TODO: write the user journey** |
| F194: Export a OpenWand conversation as a new ChatGPT conversation. | **TODO: write the user journey** |
| F195: Export a OpenWand conversation as a new Claude conversation. | **TODO: write the user journey** |
| F196: Open provider controls from the floating provider badge. | **TODO: write the user journey** |
| F197: Select provider-default or explicit agent model. | **TODO: write the user journey** |
| F198: Choose or automatically detect the agent project/workspace folder. | **TODO: write the user journey** |
| F199: Enable agent fast mode. | **TODO: write the user journey** |
| F200: Choose agent reasoning effort: provider default, low, medium, high, xhigh, max, or ultra where supported. | **TODO: write the user journey** |
| F201: Choose detailed, concise, provider, or no visible reasoning summaries. | **TODO: write the user journey** |
| F202: Require approval for agent operations. | **TODO: write the user journey** |
| F203: Allow agent edits within the selected project. | **TODO: write the user journey** |
| F204: Grant full agent access. | **TODO: write the user journey** |
| F205: Use plan-only/read-only agent mode. | **TODO: write the user journey** |
## 9. Provider accounts and connections

| Capability | User journey implementation |
|---|---|
| F206: Sign in to ChatGPT Plus/Pro in a browser. | Written path: [Click ChatGPT sign-in and recover from declined, invalid and incomplete callbacks (lines 551-568)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:551) |
| F207: Check ChatGPT sign-in status. | Written path: [Click ChatGPT sign-in and recover from declined, invalid and incomplete callbacks (lines 551-568)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:551) |
| F208: Sign out of ChatGPT. | **TODO: write the user journey** |
| F209: Sign in to GitHub with the device/browser OAuth flow. | **TODO: write the user journey** |
| F210: Check GitHub sign-in status. | **TODO: write the user journey** |
| F211: Sign out of GitHub. | **TODO: write the user journey** |
| F212: Override the GitHub OAuth client ID and scopes. | **TODO: write the user journey** |
| F213: Store and clear GitHub Copilot provider credentials. | **TODO: write the user journey** |
| F214: Check GitHub Copilot credential readiness through the app API. | **TODO: write the user journey** |
| F215: Add a provider connection. | Written path: [Add a custom provider with alias, endpoint and credential (lines 178-189)](C:/OpenWand/scripts/user_journeys/scenarios.py:178); [Discard an added connection draft and continue using the saved provider (lines 383-399)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:383); [Add, search and filter a second provider connection (lines 81-101)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:81) |
| F216: Give a connection an alias. | Written path: [Add a custom provider with alias, endpoint and credential (lines 178-189)](C:/OpenWand/scripts/user_journeys/scenarios.py:178); [Discard an unsaved provider alias change (lines 331-340)](C:/OpenWand/scripts/user_journeys/scenarios.py:331); [Save a Unicode provider alias, reopen it and restore its display name (lines 402-420)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:402) |
| F217: Store API keys in the operating-system keychain. | **TODO: write the user journey** |
| F218: Remove/clear a provider connection. | Written path: [Cancel provider removal, then save removal without breaking its sibling (lines 104-123)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:104) |
| F219: Search connections by provider or alias. | Written path: [Add, search and filter a second provider connection (lines 81-101)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:81) |
| F220: Filter All, Cloud, or Local/custom connections. | Written path: [Add, search and filter a second provider connection (lines 81-101)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:81) |
| F221: Expand or collapse large connection lists. | Written path: [Expand and collapse a large provider list without saving drafts (lines 505-522)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:505) |
| F222: Configure a custom OpenAI-compatible base URL and API key. | Written path: [Use the retained provider after another full application launch (lines 56-78)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:56); [Replace a connection key, show authentication failure and recover (lines 650-670)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:650) |
| F223: Choose a preset or custom provider endpoint. | Written path: [Add a custom provider with alias, endpoint and credential (lines 178-189)](C:/OpenWand/scripts/user_journeys/scenarios.py:178) |
| F224: Use an existing local Ollama installation and auto-start its server when needed. | **TODO: write the user journey** |
| F225: Use an LM Studio or other OpenAI-compatible endpoint through Custom. | **TODO: write the user journey** |
| F226: Refresh model names from providers that support model listing. | Written path: [Refresh provider model names through the live Settings control (lines 126-133)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:126) |
| F227: Enter an exact model name manually. | Written path: [Show a failing model probe and recover by fixing the draft model (lines 279-292)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:279); [Enter an exact model name and send a prompt through that route (lines 487-502)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:487) |
| F228: Groq. | **TODO: write the user journey** |
| F229: OpenAI API. | **TODO: write the user journey** |
| F230: Anthropic. | **TODO: write the user journey** |
| F231: Google AI Studio. | **TODO: write the user journey** |
| F232: ChatGPT Plus/Pro OAuth. | **TODO: write the user journey** |
| F233: GitHub Copilot. | **TODO: write the user journey** |
| F234: DeepSeek. | **TODO: write the user journey** |
| F235: OpenRouter. | **TODO: write the user journey** |
| F236: Mistral. | **TODO: write the user journey** |
| F237: xAI/Grok. | **TODO: write the user journey** |
| F238: Together AI. | **TODO: write the user journey** |
| F239: Cerebras. | **TODO: write the user journey** |
| F240: Z.AI/GLM. | **TODO: write the user journey** |
| F241: NVIDIA. | **TODO: write the user journey** |
| F242: SambaNova. | **TODO: write the user journey** |
| F243: GitHub Models. | **TODO: write the user journey** |
| F244: Hugging Face. | **TODO: write the user journey** |
| F245: Chutes. | **TODO: write the user journey** |
| F246: Vercel AI Gateway. | **TODO: write the user journey** |
| F247: Fireworks. | **TODO: write the user journey** |
| F248: Cohere. | **TODO: write the user journey** |
| F249: AI21. | **TODO: write the user journey** |
| F250: Nebius. | **TODO: write the user journey** |
| F251: Ollama local. | **TODO: write the user journey** |
| F252: Custom OpenAI-compatible provider. | **TODO: write the user journey** |
## 10. Model routing and model tests

| Capability | User journey implementation |
|---|---|
| F253: Choose the primary provider/model for the Chat model route. | Written path: [Select the new provider for Chat, Image and Memory routes (lines 192-201)](C:/OpenWand/scripts/user_journeys/scenarios.py:192); [Enter an exact model name and send a prompt through that route (lines 487-502)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:487) |
| F254: Add, remove, and reorder Chat model fallbacks. | Written path: [Test a working primary and a broken fallback without blaming the primary (lines 593-608)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:593); [Add model fallbacks, copy routes and remove the extra row (lines 136-152)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:136) |
| F255: **Test Chat model** from Settings. | Written path: [Test the saved Chat model from Settings (lines 261-264)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:261); [Show a failing model probe and recover by fixing the draft model (lines 279-292)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:279); [Test a working primary and a broken fallback without blaming the primary (lines 593-608)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:593); [Reject testing an unconfigured model without making a network call (lines 611-620)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:611) |
| F256: Choose the primary provider/model for the Image model route. | Written path: [Select the new provider for Chat, Image and Memory routes (lines 192-201)](C:/OpenWand/scripts/user_journeys/scenarios.py:192) |
| F257: Add, remove, and reorder Image model fallbacks. | Written path: [Add model fallbacks, copy routes and remove the extra row (lines 136-152)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:136) |
| F258: **Test Image model** from Settings. | Written path: [Test the saved Image model with an actual image request (lines 267-270)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:267) |
| F259: Choose the primary provider/model for the Memory model route. | Written path: [Select the new provider for Chat, Image and Memory routes (lines 192-201)](C:/OpenWand/scripts/user_journeys/scenarios.py:192) |
| F260: Add, remove, and reorder Memory model fallbacks. | Written path: [Add model fallbacks, copy routes and remove the extra row (lines 136-152)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:136) |
| F261: **Test Memory model** from Settings. | Written path: [Test the saved Memory model from Settings (lines 273-276)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:273) |
| F262: Copy one route's provider/model rows to all model routes with **Apply to all**. | Written path: [Add model fallbacks, copy routes and remove the extra row (lines 136-152)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:136) |
| F263: Drag model rows to change priority. | **TODO: write the user journey** |
| F264: Refresh available model IDs for an individual route row. | Written path: [Refresh provider model names through the live Settings control (lines 126-133)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:126) |
| F265: Fall through to the next configured model when a route fails. | Written path: [Recover through a fallback and cool down the failing primary (lines 155-179)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:155) |
| F266: Temporarily cool down a failing route before retrying it later. | Written path: [Recover through a fallback and cool down the failing primary (lines 155-179)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:155) |
| F267: Adapt to provider differences such as streaming, tools, images, token parameters, and reasoning controls. | **TODO: write the user journey** |
| F268: Show warnings when a chosen model/provider cannot satisfy an enabled capability. | **TODO: write the user journey** |
| F269: Use OpenWand, ChatGPT, or Claude Agent as the conversation execution engine. | **TODO: write the user journey** |
| F270: Choose OpenWand or the selected agent as conversation owner. | **TODO: write the user journey** |
| F271: Edit separate system prompts for OpenWand, ChatGPT, and Claude conversations. | **TODO: write the user journey** |
## 11. Text to speech, speech to text, dictation, and live voice

| Capability | User journey implementation |
|---|---|
| F272: Disable text to speech while retaining manual read-aloud/test features. | **TODO: write the user journey** |
| F273: Automatically speak assistant replies. | **TODO: write the user journey** |
| F274: Read selected text aloud on demand. | **TODO: write the user journey** |
| F275: Stop current speech playback. | **TODO: write the user journey** |
| F276: Set global TTS playback volume. | **TODO: write the user journey** |
| F277: Set normal and held/fast-forward TTS playback speed. | **TODO: write the user journey** |
| F278: Configure read-aloud minimum and maximum chunk size. | **TODO: write the user journey** |
| F279: Test the selected TTS provider with **Test TTS**. | **TODO: write the user journey** |
| F280: Use Cartesia TTS and configure its key and voice ID. | **TODO: write the user journey** |
| F281: Install and use ElevenLabs TTS; configure key, voice, and model. | **TODO: write the user journey** |
| F282: Use OpenAI TTS; configure voice and model. | **TODO: write the user journey** |
| F283: Use an OpenAI-compatible `/audio/speech` endpoint; configure URL, key, voice, model, and sample rate. | **TODO: write the user journey** |
| F284: Use a local GPT-SoVITS server; configure reference audio/transcript/languages and sample rate. | **TODO: write the user journey** |
| F285: Install and use local Kokoro TTS. | **TODO: write the user journey** |
| F286: Configure Kokoro voice, language code, device, speed, and sample rate. | **TODO: write the user journey** |
| F287: Download, repair, or update Kokoro voice-model assets. | **TODO: write the user journey** |
| F288: Choose automatic, CPU, or CUDA speech device where supported. | **TODO: write the user journey** |
| F289: Install local faster-whisper speech-to-text. | **TODO: write the user journey** |
| F290: Choose Whisper model size. | **TODO: write the user journey** |
| F291: Choose STT device and compute type. | **TODO: write the user journey** |
| F292: Choose automatic or explicit speech language. | **TODO: write the user journey** |
| F293: Configure Whisper beam size. | **TODO: write the user journey** |
| F294: Transcribe long recordings in overlapping background chunks. | **TODO: write the user journey** |
| F295: Configure first STT chunk time, cadence, live-edge delay, and overlap. | **TODO: write the user journey** |
| F296: Review a voice transcript and its context before asking. | **TODO: write the user journey** |
| F297: Send a voice transcript directly without review. | **TODO: write the user journey** |
| F298: Dictate raw speech into the currently focused field. | **TODO: write the user journey** |
| F299: Clean dictated speech with the LLM before pasting it. | **TODO: write the user journey** |
| F300: Install live-voice support. | **TODO: write the user journey** |
| F301: Start and stop a hands-free Gemini Live conversation. | **TODO: write the user journey** |
| F302: Display live user and assistant transcripts. | **TODO: write the user journey** |
| F303: Interrupt OpenWand by speaking over it when full duplex is enabled. | **TODO: write the user journey** |
| F304: Pause the microphone while OpenWand speaks in speaker/half-duplex mode. | **TODO: write the user journey** |
| F305: Choose the live-conversation provider, model, and voice. | **TODO: write the user journey** |
## 12. Memory

| Capability | User journey implementation |
|---|---|
| F306: Store durable facts with phrases such as “remember that,” “note that,” or “keep in mind.” | **TODO: write the user journey** |
| F307: Forget/remove remembered facts through supported memory commands. | **TODO: write the user journey** |
| F308: Let the model search memory when a prompt needs it. | Written path: [Save a memory through a model tool and find it in the viewer (lines 470-484)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:470) |
| F309: Let the model save a durable memory when permitted. | Written path: [Save a memory through a model tool and find it in the viewer (lines 470-484)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:470) |
| F310: Automatically extract long-term facts from conversations. | **TODO: write the user journey** |
| F311: Automatically consolidate memory on a configurable interval. | **TODO: write the user journey** |
| F312: Set how many facts are retrieved for a query. | **TODO: write the user journey** |
| F313: Set the short-term-memory token budget before compression. | **TODO: write the user journey** |
| F314: Keep General memory separate from project memory. | Written path: [Edit a memory fact, move it between scopes and refresh (lines 231-241)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:231) |
| F315: Open the Long-term Memory viewer. | Written path: [Open Memory and Addon Manager from the running app (lines 343-351)](C:/OpenWand/scripts/user_journeys/scenarios.py:343); [Add a memory fact and reopen the actual Memory viewer (lines 354-367)](C:/OpenWand/scripts/user_journeys/scenarios.py:354) |
| F316: View facts grouped by project. | Written path: [Edit a memory fact, move it between scopes and refresh (lines 231-241)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:231) |
| F317: Add a fact manually and choose its project. | Written path: [Add a memory fact and reopen the actual Memory viewer (lines 354-367)](C:/OpenWand/scripts/user_journeys/scenarios.py:354) |
| F318: Click and edit a fact. | Written path: [Edit a memory fact, move it between scopes and refresh (lines 231-241)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:231) |
| F319: Move/change a fact's project. | Written path: [Edit a memory fact, move it between scopes and refresh (lines 231-241)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:231) |
| F320: Delete a fact. | Written path: [Cancel memory deletion, then delete and reopen the viewer (lines 244-260)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:244) |
| F321: Refresh the memory list. | Written path: [Add a memory fact and reopen the actual Memory viewer (lines 354-367)](C:/OpenWand/scripts/user_journeys/scenarios.py:354); [Cancel memory deletion, then delete and reopen the viewer (lines 244-260)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:244) |
## 13. Privacy and secret handling

| Capability | User journey implementation |
|---|---|
| F322: Send messages with privacy filtering off. | **TODO: write the user journey** |
| F323: Redact private information with the built-in local filter. | Written path: [Enable privacy filtering and verify the actual outgoing request (lines 410-432)](C:/OpenWand/scripts/user_journeys/scenarios.py:410); [Review privacy redaction before permitting a network request (lines 263-279)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:263) |
| F324: Install, repair, and use the advanced local privacy model. | **TODO: write the user journey** |
| F325: Remove the advanced privacy model. | **TODO: write the user journey** |
| F326: Keep the built-in filter active alongside Advanced mode. | **TODO: write the user journey** |
| F327: Review detected private information and the redacted request before sending. | Written path: [Review privacy redaction before permitting a network request (lines 263-279)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:263) |
| F328: Cancel a request from the privacy review. | Written path: [Cancel a privacy review and send a later clean prompt (lines 282-305)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:282) |
| F329: Apply privacy handling to normal requests, tool results, and local-model requests. | Written path: [Enable privacy filtering and verify the actual outgoing request (lines 410-432)](C:/OpenWand/scripts/user_journeys/scenarios.py:410) |
| F330: Store provider credentials outside the plain settings file in the OS keychain. | **TODO: write the user journey** |
| F331: Mask stored secrets in Settings. | **TODO: write the user journey** |
| F332: Reset all settings and remove saved keychain secrets after confirmation. | **TODO: write the user journey** |
## 14. Built-in model tools and permissions

| Capability | User journey implementation |
|---|---|
| F333: Search the web with `web_search`. | **TODO: write the user journey** |
| F334: Read open documents/current pages with `get_context`. | **TODO: write the user journey** |
| F335: Retrieve a specific website with `retrieve_website`. | **TODO: write the user journey** |
| F336: Capture the screen with `capture_screen`. | **TODO: write the user journey** |
| F337: Search long-term memory with `memory_search`. | **TODO: write the user journey** |
| F338: Save durable memory with `memory_save`. | **TODO: write the user journey** |
| F339: Read local Git status with `git_status`. | **TODO: write the user journey** |
| F340: Read local Git diff with `git_diff`. | **TODO: write the user journey** |
| F341: List allowed folders with `list_files`. | **TODO: write the user journey** |
| F342: Read allowed files with `read_file`. | Written path: [Read-only Files reads a document and withholds writing tools (lines 394-405)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:394) |
| F343: Create allowed files with `create_file`. | Written path: [Preview a file change, approve it and verify the actual file (lines 408-422)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:408); [Create and overwrite scoped files with automatic permission (lines 438-450)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:438) |
| F344: Patch allowed files with `edit_file`. | **TODO: write the user journey** |
| F345: Create or overwrite allowed files with `write_file`. | Written path: [Create and overwrite scoped files with automatic permission (lines 438-450)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:438) |
| F346: Fetch GitHub repository metadata with `github_repo`. | **TODO: write the user journey** |
| F347: Fetch a GitHub issue or pull request with `github_issue`. | **TODO: write the user journey** |
| F348: Set each local-file tool to Off or Auto for an individual shortcut. | **TODO: write the user journey** |
| F349: Set installed/add-on tools to Off or Auto for an individual shortcut. | **TODO: write the user journey** |
| F350: Group MCP tools by server and enable/disable a complete server. | **TODO: write the user journey** |
| F351: Override an individual MCP tool or let it follow its server setting. | **TODO: write the user journey** |
| F352: Ask for approval and show a diff before file writes when configured. | Written path: [Preview a file change, approve it and verify the actual file (lines 408-422)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:408) |
| F353: Approve a proposed live file operation. | Written path: [Preview a file change, approve it and verify the actual file (lines 408-422)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:408) |
| F354: Request an alternate operation and provide feedback. | **TODO: write the user journey** |
| F355: Decline a proposed live file operation and provide feedback. | Written path: [Decline a file change and verify that no file is written (lines 425-435)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:425) |
| F356: Enforce per-request tool-call and tool-output budgets. | **TODO: write the user journey** |
| F357: Show tool activity/trace in chat when enabled. | **TODO: write the user journey** |
## 15. Add-ons and MCP extensions

| Capability | User journey implementation |
|---|---|
| F358: Open the Addon Manager. | Written path: [Open Memory and Addon Manager from the running app (lines 343-351)](C:/OpenWand/scripts/user_journeys/scenarios.py:343); [Open Addon Manager from the running app's tray (lines 102-109)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:102) |
| F359: Open the add-ons folder. | **TODO: write the user journey** |
| F360: Install an add-on archive. | Written path: [Cancel choosing an addon archive without installing anything (lines 112-122)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:112); [Install a chosen addon archive and show its pending access review (lines 125-137)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:125); [Reject an addon archive with a path escaping its package (lines 292-309)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:292) |
| F361: Install an add-on from a folder. | Written path: [Install an addon from a chosen folder through the real directory picker (lines 276-289)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:276); [Install and approve the shipped Shared Workspace addon (lines 33-48)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:33) |
| F362: Enable or disable an installed add-on. | Written path: [Disable an addon and remove its effects from the next prompt (lines 218-232)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:218); [Re-enable an installed addon without losing its saved settings (lines 235-248)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:235); [Finish addon journeys with contributed hooks disabled (lines 312-322)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:312); [Stop the workspace service, disable its addon and return to Chat (lines 160-178)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:160) |
| F363: Open an add-on's settings. | Written path: [Edit addon text, checkbox, number and choice settings and reopen them (lines 176-194)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:176) |
| F364: Edit checkbox, number, text, and choice settings supplied by an add-on. | Written path: [Edit addon text, checkbox, number and choice settings and reopen them (lines 176-194)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:176) |
| F365: Open and review an add-on's logs. | Written path: [Open addon logs and verify its work came from a separate process (lines 251-263)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:251) |
| F366: Install, rebuild, or repair an add-on's isolated dependencies after approval. | **TODO: write the user journey** |
| F367: Run add-ons in isolated host processes. | Written path: [Approve an addon and use its response hook and model tool listing (lines 157-173)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:157); [Call an installed addon's tool through a real model tool loop (lines 207-215)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:207); [Open addon logs and verify its work came from a separate process (lines 251-263)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:251) |
| F368: Enforce permissions declared by an add-on manifest. | Written path: [Install a chosen addon archive and show its pending access review (lines 125-137)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:125); [Decline addon access and verify its hooks and tools do not run (lines 140-154)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:140); [Approve an addon and use its response hook and model tool listing (lines 157-173)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:157); [Reject an addon archive with a path escaping its package (lines 292-309)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:292); [Install and approve the shipped Shared Workspace addon (lines 33-48)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:33); [Deny model file creation while the workspace addon setting is Off (lines 64-71)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:64) |
| F369: Let add-ons contribute context before a query. | Written path: [Apply an approved addon's before-query hook to a Chat prompt (lines 197-204)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:197) |
| F370: Let add-ons contribute model-callable tools. | Written path: [Approve an addon and use its response hook and model tool listing (lines 157-173)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:157); [Call an installed addon's tool through a real model tool loop (lines 207-215)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:207); [Disable an addon and remove its effects from the next prompt (lines 218-232)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:218); [Ask to open Shared Workspace and connect its real local viewer (lines 51-61)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:51); [Deny model file creation while the workspace addon setting is Off (lines 64-71)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:64) |
| F371: Let add-ons process a response after completion. | Written path: [Approve an addon and use its response hook and model tool listing (lines 157-173)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:157) |
| F372: Let add-ons add intent actions and action rows. | **TODO: write the user journey** |
| F373: Let add-ons add global shortcuts. | **TODO: write the user journey** |
| F374: Let add-ons add tray actions and notifications. | Written path: [Run a contributed addon tray action without sending a model request (lines 266-273)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:266) |
| F375: Let add-ons add Settings fields. | Written path: [Edit addon text, checkbox, number and choice settings and reopen them (lines 176-194)](C:/OpenWand/scripts/user_journeys/addon_scenarios.py:176) |
| F376: Let add-ons perform capped auxiliary LLM actions. | **TODO: write the user journey** |
| F377: Discover configured MCP servers and expose their tools through the bridge. | **TODO: write the user journey** |
| F378: Expose OpenWand context MCP operations for selected text, clipboard, active window, browser page, and screen snip. | **TODO: write the user journey** |
## 16. Multi-agent tasks

| Capability | User journey implementation |
|---|---|
| F379: Start an agent task from the tray menu. | Written path: [Open the agent task designer from the tray and cancel it (lines 51-60)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:51); [Start an agent task and receive its saved final report (lines 108-120)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:108); [Continue ordinary Chat after completing and cancelling agent tasks (lines 217-223)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:217) |
| F380: Copy task settings from the last agent task. | Written path: [Copy the last started agent task into a new task designer (lines 123-134)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:123) |
| F381: Set the task title and objective. | Written path: [Reject starting an agent task without a title (lines 63-74)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:63); [Reject starting an agent task without an objective (lines 77-89)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:77); [Preview a scoped task specification before starting work (lines 92-105)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:92); [Start an agent task and receive its saved final report (lines 108-120)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:108) |
| F382: Copy relevant context from the current application. | **TODO: write the user journey** |
| F383: Add required task context manually. | **TODO: write the user journey** |
| F384: Choose an agent provider/model and fallback models. | **TODO: write the user journey** |
| F385: Choose the task scope folder. | Written path: [Preview a scoped task specification before starting work (lines 92-105)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:92); [Run an agent team that creates a scoped file and hands work between roles (lines 137-149)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:137); [Approve a scoped agent file write after inspecting the pending request (lines 181-195)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:181); [Decline an agent file write and verify that the file is not created (lines 198-214)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:198) |
| F386: Configure allowed and blocked file globs. | **TODO: write the user journey** |
| F387: Use the coordinator, builder, and reviewer defaults. | Written path: [Run an agent team that creates a scoped file and hands work between roles (lines 137-149)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:137) |
| F388: Add or remove agents. | **TODO: write the user journey** |
| F389: Customize each agent's name, role, model, and instructions. | **TODO: write the user journey** |
| F390: Start with a parallel read-only briefing. | **TODO: write the user journey** |
| F391: Run implementer agents in parallel with file leases. | **TODO: write the user journey** |
| F392: Add or remove agent-to-agent communications. | **TODO: write the user journey** |
| F393: Configure sender, recipient, trigger, and message for a communication. | **TODO: write the user journey** |
| F394: Create paired two-way exchanges. | **TODO: write the user journey** |
| F395: Reset the communication map to defaults. | **TODO: write the user journey** |
| F396: Open and refresh the Agent Communication Map. | **TODO: write the user journey** |
| F397: Set explicit completion criteria. | **TODO: write the user journey** |
| F398: Preview the generated task specification. | Written path: [Preview a scoped task specification before starting work (lines 92-105)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:92) |
| F399: Start or cancel the configured task. | Written path: [Start an agent task and receive its saved final report (lines 108-120)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:108); [Run an agent team that creates a scoped file and hands work between roles (lines 137-149)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:137) |
| F400: Review and approve an agent permission request. | Written path: [Approve a scoped agent file write after inspecting the pending request (lines 181-195)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:181) |
| F401: Decline an agent permission request. | Written path: [Decline an agent file write and verify that the file is not created (lines 198-214)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:198) |
| F402: Watch the live Meeting view and agent cards. | **TODO: write the user journey** |
| F403: View Live Log, Model Trace, and Final Report tabs. | Written path: [Start an agent task and receive its saved final report (lines 108-120)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:108) |
| F404: Drag/resize agent cards and reset their layout. | **TODO: write the user journey** |
| F405: Inspect agent status, health, messages, and shared-board activity. | **TODO: write the user journey** |
| F406: View the task diff. | **TODO: write the user journey** |
| F407: Open the task memory/result folder. | **TODO: write the user journey** |
| F408: Open the task scope folder. | **TODO: write the user journey** |
| F409: Retry a task. | **TODO: write the user journey** |
| F410: Continue a completed or interrupted task. | **TODO: write the user journey** |
| F411: Nudge a selected agent with a message. | **TODO: write the user journey** |
| F412: Pause after the current turn and resume later. | **TODO: write the user journey** |
| F413: Cancel a running task. | Written path: [Cancel a running agent task and return to usable controls (lines 152-165)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:152) |
| F414: Open Agent Task History. | Written path: [Reopen a finished agent run from history and inspect its report and logs (lines 168-178)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:168) |
| F415: Review a historical task's Summary, Run Log, Model Trace, and Diff. | Written path: [Reopen a finished agent run from history and inspect its report and logs (lines 168-178)](C:/OpenWand/scripts/user_journeys/agent_scenarios.py:168) |
| F416: Refresh history and reopen result folders. | **TODO: write the user journey** |
## 17. Settings, profiles, appearance, and behavior

| Capability | User journey implementation |
|---|---|
| F417: Navigate General, Connections, Model routing, Voice & audio, Shortcuts, Prompts & context, Advanced, and About pages. | Written path: [Visit all Settings pages and return to Chat (lines 305-314)](C:/OpenWand/scripts/user_journeys/scenarios.py:305) |
| F418: Search Settings and jump to matching fields. | Written path: [Search Settings and restore navigation after no matches (lines 308-317)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:308) |
| F419: Load a built-in configuration profile. | **TODO: write the user journey** |
| F420: Create/save a custom profile. | Written path: [Cancel creating a custom profile and retain the saved profile list (lines 623-633)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:623); [Create and rename a custom profile through real dialogs (lines 320-344)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:320) |
| F421: Rename a custom profile. | Written path: [Create and rename a custom profile through real dialogs (lines 320-344)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:320) |
| F422: Delete a custom profile. | Written path: [Delete an inactive custom profile with Cancel and confirmation (lines 525-548)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:525) |
| F423: Run the setup check from Settings. | **TODO: write the user journey** |
| F424: Run the guided profile setup from Settings. | **TODO: write the user journey** |
| F425: Save settings changes. | Written path: [Save provider settings, close and reopen Settings (lines 204-213)](C:/OpenWand/scripts/user_journeys/scenarios.py:204); [Change appearance, save it and continue prompting (lines 317-328)](C:/OpenWand/scripts/user_journeys/scenarios.py:317); [Reopen the saved provider before the basic user journeys (lines 71-88)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:71); [Cancel resetting a Settings page and preserve saved settings (lines 370-380)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:370); [Save a Unicode provider alias, reopen it and restore its display name (lines 402-420)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:402); [Confirm an Advanced page reset without losing the provider or conversation (lines 439-460)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:439); [Use the retained provider after another full application launch (lines 56-78)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:56); [After a full app restart, reopen saved provider and conversation (lines 455-465)](C:/OpenWand/scripts/user_journeys/scenarios.py:455) |
| F426: Cancel/discard settings changes. | Written path: [Discard an unsaved provider alias change (lines 331-340)](C:/OpenWand/scripts/user_journeys/scenarios.py:331); [Discard an added connection draft and continue using the saved provider (lines 383-399)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:383); [Keep unsaved Settings when guided setup asks to save first (lines 575-590)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:575); [Cancel provider removal, then save removal without breaking its sibling (lines 104-123)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:104); [Expand and collapse a large provider list without saving drafts (lines 505-522)](C:/OpenWand/scripts/user_journeys/extended_scenarios.py:505) |
| F427: Reset only the current Settings page. | Written path: [Cancel resetting a Settings page and preserve saved settings (lines 370-380)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:370); [Confirm an Advanced page reset without losing the provider or conversation (lines 439-460)](C:/OpenWand/scripts/user_journeys/basic_scenarios.py:439) |
| F428: Reset every setting after confirmation. | **TODO: write the user journey** |
| F429: Choose System, Light, or Dark theme. | Written path: [Change appearance, save it and continue prompting (lines 317-328)](C:/OpenWand/scripts/user_journeys/scenarios.py:317) |
| F430: Customize background, surface, text, and accent colors. | **TODO: write the user journey** |
| F431: Customize icon size. | **TODO: write the user journey** |
| F432: Customize bubble width, line count, and font size. | **TODO: write the user journey** |
| F433: Customize bubble background, text, and spoken-word highlight colors. | **TODO: write the user journey** |
| F434: Enable or disable bubble wheel scrolling and spoken-line snap-back. | **TODO: write the user journey** |
| F435: Set bubble text reveal speed and held fast-forward speed. | **TODO: write the user journey** |
| F436: Set bubble display/auto-hide delay and scroll snap delay. | **TODO: write the user journey** |
| F437: Choose app UI language: system, English, Chinese, Traditional Chinese, Spanish, or French. | **TODO: write the user journey** |
| F438: Choose assistant reply language or match the user's language. | **TODO: write the user journey** |
| F439: Edit separate OpenWand, ChatGPT, and Claude system prompts. | **TODO: write the user journey** |
## 18. Optional installer controls

| Capability | User journey implementation |
|---|---|
| F440: Watch live output and elapsed time while an optional component installs. | **TODO: write the user journey** |
| F441: Cancel a running optional installer. | **TODO: write the user journey** |
| F442: Copy the installer log. | **TODO: write the user journey** |
| F443: Open the installer log folder. | **TODO: write the user journey** |
| F444: Close the installer after it finishes. | **TODO: write the user journey** |
| F445: Restart OpenWand immediately when an installed component requires restart. | **TODO: write the user journey** |
| F446: Retain a log/status file for failed or interrupted optional installs. | **TODO: write the user journey** |
## 19. Updates, diagnostics, uninstall, and resilience

| Capability | User journey implementation |
|---|---|
| F447: Show the installed OpenWand version. | **TODO: write the user journey** |
| F448: Check GitHub Releases for a newer packaged build. | **TODO: write the user journey** |
| F449: Download and apply a packaged update through the update flow. | **TODO: write the user journey** |
| F450: Pull the latest `origin/main` for a supported source checkout. | **TODO: write the user journey** |
| F451: Report update progress and errors. | **TODO: write the user journey** |
| F452: Create a bounded, redacted crash-report ZIP. | **TODO: write the user journey** |
| F453: Reveal the created crash report in Explorer/Finder. | **TODO: write the user journey** |
| F454: Exclude chats, memory, settings, environment files, and keychain files from the crash bundle. | **TODO: write the user journey** |
| F455: Review the crash ZIP before sharing it. | **TODO: write the user journey** |
| F456: Record runtime and crash logs for diagnosis. | **TODO: write the user journey** |
| F457: Show runtime status for supported worker-host configurations. | **TODO: write the user journey** |
| F458: Recover or recommend action after worker/model/audio failures. | **TODO: write the user journey** |
| F459: Confirm the exact uninstall plan before removal. | **TODO: write the user journey** |
| F460: Uninstall the app, its data, settings, chats, memory, add-ons, tools, logs, updates, optional packages, and OpenWand-owned local AI assets. | **TODO: write the user journey** |
| F461: Remove a source checkout only when that checkout is explicitly included in the confirmed uninstall plan. | **TODO: write the user journey** |
| F462: Run the uninstaller as a detached self-removing process after OpenWand closes. | **TODO: write the user journey** |
## 20. Cross-platform desktop integration

| Capability | User journey implementation |
|---|---|
| F463: Register global hotkeys on Windows, macOS, and Linux through platform-specific backends. | **TODO: write the user journey** |
| F464: Read selected/focused text using native accessibility/UI APIs where available. | **TODO: write the user journey** |
| F465: Read and restore clipboard content safely around capture/paste operations. | **TODO: write the user journey** |
| F466: Paste generated or dictated text back into the previously focused application. | **TODO: write the user journey** |
| F467: Capture screen/app regions on multi-monitor desktops. | **TODO: write the user journey** |
| F468: Use macOS helper/Accessibility flows where native permissions are required. | **TODO: write the user journey** |
| F469: Use Linux AT-SPI/X11/Wayland-compatible fallbacks where available. | **TODO: write the user journey** |
| F470: Use Windows native focused-control, clipboard, and hotkey integrations. | **TODO: write the user journey** |
| F471: Keep windows on screen and provide standard close/minimize controls where appropriate. | **TODO: write the user journey** |
| F472: Use the operating-system file browser to reveal logs, reports, task folders, add-ons, and conversation files. | **TODO: write the user journey** |

## Product surfaces newer than the older inventory

These also need complete journeys; the 472-entry inventory is not the end of the task.

| Surface | User journeys still needed | Product source |
|---|---|---|
| Shared Workspace | Written paths below cover opening, permission refusal, create/edit/rename/trash, empty task validation, reconnect and stop. Remaining: agent change review, apply/reject, stale/conflicting changes, richer previews and task recovery | [Workspace window](C:/OpenWand/ui/virtual_workspace_window.py), [changes](C:/OpenWand/core/workspace_changes.py) |
| App actions | Discover an available app action, review its plan, approve/decline, execute, verify the target application's result, recover from failure | [Runtime routing](C:/OpenWand/runtime/supervisor/flows.py) |

The external provider/browser/desktop substitutes are named in each execution report. Successful real sign-in, live service compatibility, native permissions and release installation require additional evidence.

## Written Shared Workspace paths

- [Install and approve the shipped Shared Workspace addon (lines 33-48)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:33)
- [Ask to open Shared Workspace and connect its real local viewer (lines 51-61)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:51)
- [Deny model file creation while the workspace addon setting is Off (lines 64-71)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:64)
- [Create a workspace folder and text document from its file explorer (lines 74-86)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:74)
- [Open, edit and save a document inside Shared Workspace (lines 89-100)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:89)
- [Rename a workspace file with F2 and retain its saved contents (lines 103-111)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:103)
- [Cancel deleting a workspace file and preserve it (lines 114-120)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:114)
- [Confirm workspace deletion and retain a recoverable trash copy (lines 123-133)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:123)
- [Reject an empty Shared Workspace task without starting a model request (lines 136-143)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:136)
- [Close and reopen the Shared Workspace viewer without losing the session (lines 146-157)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:146)
- [Stop the workspace service, disable its addon and return to Chat (lines 160-178)](C:/OpenWand/scripts/user_journeys/workspace_scenarios.py:160)
