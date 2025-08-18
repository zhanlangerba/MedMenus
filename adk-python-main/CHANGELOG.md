# Changelog

## [1.10.0](https://github.com/google/adk-python/compare/v1.9.0...v1.10.0) (2025-08-07)

### Features

* [Live] Implement Live Session Resumption ([71fbc92](https://github.com/google/adk-python/commit/71fbc9275b3d74700ec410cb4155ba0cb18580b7))
* [Tool] Support parallel execution of parallel function calls ([57cd41f](https://github.com/google/adk-python/commit/57cd41f424b469fb834bb8f2777b5f7be9aa6cdf))
* [Models] Allow max tokens to be customizable in Claude ([7556ebc](https://github.com/google/adk-python/commit/7556ebc76abd3c776922c2803aed831661cf7f82))
* [Tool] Create enterprise_web_search_tool as a tool instance ([0e28d64](https://github.com/google/adk-python/commit/0e28d64712e481cfd3b964be0166f529657024f6))

### Bug Fixes

* Fix shared default plugin manager and cost manager instances among multiple invocations ([423542a](https://github.com/google/adk-python/commit/423542a43fb8316195e9f79d97f87593751bebd3))
* Correct the type annotation in anthropic_llm implementation ([97318bc](https://github.com/google/adk-python/commit/97318bcd199acdacadfe8664da3fbfc3c806cdd2))
* Fix adk deploy cloud_run cli, which was broken in v1.9.0 ([e41dbcc](https://github.com/google/adk-python/commit/e41dbccf7f610e249108f9321f60f71fe2cc10f4))
* Remove thoughts from contents in llm requests from history contents ([d620bcb](https://github.com/google/adk-python/commit/d620bcb384d3068228ea2059fb70274e68e69682))
* Annotate response type as None for transfer_to_agent tool ([86a4487](https://github.com/google/adk-python/commit/86a44873e9b2dfc7e62fa31a9ac3be57c0bbff7b))
* Fix incompatible a2a sdk changes ([faadef1](https://github.com/google/adk-python/commit/faadef167ee8e4dd1faf4da5685a577c3155556e))
* Fix adk cli options and method parameters mismatching ([8ef2177](https://github.com/google/adk-python/commit/8ef2177658fbfc74b1a74b0c3ea8150bae866796))

### Improvements

* Add Github workflow config for the ADK Answering agent ([8dc0c94](https://github.com/google/adk-python/commit/8dc0c949afb9024738ff7ac1b2c19282175c3200))
* Import AGENT_CARD_WELL_KNOWN_PATH from adk instead of from a2a directly ([37dae9b](https://github.com/google/adk-python/commit/37dae9b631db5060770b66fce0e25cf0ffb56948))
* Make `LlmRequest.LiveConnectConfig` field default to a factory ([74589a1](https://github.com/google/adk-python/commit/74589a1db7df65e319d1ad2f0676ee0cf5d6ec1d))
* Update the prompt to make the ADK Answering Agent more objective ([2833030](https://github.com/google/adk-python/commit/283303032a174d51b8d72f14df83c794d66cb605))
* Add sample agent for testing parallel functions execution ([90b9193](https://github.com/google/adk-python/commit/90b9193a20499b8dd7f57d119cda4c534fcfda10))
* Hide the ask_data_insights tool until the API is publicly available ([bead607](https://github.com/google/adk-python/commit/bead607364be7ac8109357c9d3076d9b345e9e8a))
* Change `LlmRequest.config`'s default value to be `types.GenerateContentConfig()` ([041f04e](https://github.com/google/adk-python/commit/041f04e89cee30532facccce4900d10f1b8c69ce))
* Prevent triggering of _load_from_yaml_config in AgentLoader ([db975df](https://github.com/google/adk-python/commit/db975dfe2a09a6d056d02bc03c1247ac10f6da7d))

### Documentation

* Fix typos ([16a15c8](https://github.com/google/adk-python/commit/16a15c8709b47c9bebe7cffe888e8e7e48ec605a))


## [1.9.0](https://github.com/google/adk-python/compare/v1.8.0...v1.9.0) (2025-07-31)


### Features

* [CLI] Add `-v`, `--verbose` flag to enable DEBUG logging as a shortcut for `--log_level DEBUG` ([3be0882](https://github.com/google/adk-python/commit/3be0882c63bf9b185c34bcd17e03769b39f0e1c5))
* [CLI] Add a CLI option to update an agent engine instance ([206a132](https://github.com/google/adk-python/commit/206a13271e5f1bb0bb8114b3bb82f6ec3f030cd7))
* [CLI] Modularize fast_api.py to allow simpler construction of API Server ([bfc203a](https://github.com/google/adk-python/commit/bfc203a92fdfbc4abaf776e76dca50e7ca59127b), [dfc25c1](https://github.com/google/adk-python/commit/dfc25c17a98aaad81e1e2f140db83d17cd78f393), [e176f03](https://github.com/google/adk-python/commit/e176f03e8fe13049187abd0f14e63afca9ccff01))
* [CLI] Refactor AgentLoader into base class and add InMemory impl alongside existing filesystem impl ([bda3df2](https://github.com/google/adk-python/commit/bda3df24802d0456711a5cd05544aea54a13398d))
* [CLI] Respect the .ae_ignore file when deploying to agent engine ([f29ab5d](https://github.com/google/adk-python/commit/f29ab5db0563a343d6b8b437a12557c89b7fc98b))
* [Core] Add new callbacks to handle tool and model errors ([00afaaf](https://github.com/google/adk-python/commit/00afaaf2fc18fba85709754fb1037bb47f647243))
* [Core] Add sample plugin for logging ([20537e8](https://github.com/google/adk-python/commit/20537e8bfa31220d07662dad731b4432799e1802))
* [Core] Expose Gemini RetryOptions to client ([1639298](https://github.com/google/adk-python/commit/16392984c51b02999200bd4f1d6781d5ec9054de))
* [Evals] Added an Fast API new endpoint to serve eval metric info ([c69dcf8](https://github.com/google/adk-python/commit/c69dcf87795c4fa2ad280b804c9b0bd3fa9bf06f))
* [Evals] Refactored AgentEvaluator and updated it to use LocalEvalService ([1355bd6](https://github.com/google/adk-python/commit/1355bd643ba8f7fd63bcd6a7284cc48e325d138e))


### Bug Fixes

* Add absolutize_imports option when deploying to agent engine ([fbe6a7b](https://github.com/google/adk-python/commit/fbe6a7b8d3a431a1d1400702fa534c3180741eb3))
* Add space to allow adk deploy cloud_run --a2a ([70c4616](https://github.com/google/adk-python/commit/70c461686ec2c60fcbaa384a3f1ea2528646abba))
* Copy the original function call args before passing it to callback or tools to avoid being modified ([3432b22](https://github.com/google/adk-python/commit/3432b221727b52af2682d5bf3534d533a50325ef))
* Eval module not found exception string ([7206e0a](https://github.com/google/adk-python/commit/7206e0a0eb546a66d47fb411f3fa813301c56f42))
* Fix incorrect token count mapping in telemetry ([c8f8b4a](https://github.com/google/adk-python/commit/c8f8b4a20a886a17ce29abd1cfac2858858f907d))
* Import cli's artifact dependencies directly ([282d67f](https://github.com/google/adk-python/commit/282d67f253935af56fae32428124a385f812c67d))
* Keep existing header values while merging tracking headers for `llm_request.config.http_options` in `Gemini.generate_content_async` ([6191412](https://github.com/google/adk-python/commit/6191412b07c3b5b5a58cf7714e475f63e89be847))
* Merge tracking headers even when `llm_request.config.http_options` is not set in `Gemini.generate_content_async` ([ec8dd57](https://github.com/google/adk-python/commit/ec8dd5721aa151cfc033cc3aad4733df002ae9cb))
* Restore bigquery sample agent to runnable form ([16e8419](https://github.com/google/adk-python/commit/16e8419e32b54298f782ba56827e5139effd8780))
* Return session state in list_session API endpoint ([314d6a4](https://github.com/google/adk-python/commit/314d6a4f95c6d37c7da3afbc7253570564623322))
* Runner was expecting Event object instead of Content object when using early exist feature ([bf72426](https://github.com/google/adk-python/commit/bf72426af2bfd5c2e21c410005842e48b773deb3))
* Unable to acquire impersonated credentials ([9db5d9a](https://github.com/google/adk-python/commit/9db5d9a3e87d363c1bac0f3d8e45e42bd5380d3e))
* Update `agent_card_builder` to follow grammar rules ([9c0721b](https://github.com/google/adk-python/commit/9c0721beaa526a4437671e6cc70915073be835e3)), closes [#2223](https://github.com/google/adk-python/issues/2223)
* Use correct type for actions parameter in ApplicationIntegrationToolset ([ce7253f](https://github.com/google/adk-python/commit/ce7253f63ff8e78bccc7805bd84831f08990b881))


### Documentation

* Update documents about the information of vibe coding ([0c85587](https://github.com/google/adk-python/commit/0c855877c57775ad5dad930594f9f071164676da))


## [1.8.0](https://github.com/google/adk-python/compare/v1.7.0...v1.8.0) (2025-07-23)

### Features

* [Core]Add agent card builder ([18f5bea](https://github.com/google/adk-python/commit/18f5bea411b3b76474ff31bfb2f62742825b45e5))
* [Core]Add an to_a2a util to convert adk agent to A2A ASGI application ([a77d689](https://github.com/google/adk-python/commit/a77d68964a1c6b7659d6117d57fa59e43399e0c2))
* [Core]Add camel case converter for agents ([0e173d7](https://github.com/google/adk-python/commit/0e173d736334f8c6c171b3144ac6ee5b7125c846))
* [Evals]Use LocalEvalService to run all evals in cli and web ([d1f182e](https://github.com/google/adk-python/commit/d1f182e8e68c4a5a4141592f3f6d2ceeada78887))
* [Evals]Enable FinalResponseMatchV2 metric as an experiment ([36e45cd](https://github.com/google/adk-python/commit/36e45cdab3bbfb653eee3f9ed875b59bcd525ea1))
* [Models]Add support for `model-optimizer-*` family of models in vertex ([ffe2bdb](https://github.com/google/adk-python/commit/ffe2bdbe4c2ea86cc7924eb36e8e3bb5528c0016))
* [Services]Added a sample for History Management ([67284fc](https://github.com/google/adk-python/commit/67284fc46667b8c2946762bc9234a8453d48a43c))
* [Services]Support passing fully qualified agent engine resource name when constructing session service and memory service ([2e77804](https://github.com/google/adk-python/commit/2e778049d0a675e458f4e
35fe4104ca1298dbfcf))
* [Tools]Add ComputerUseToolset ([083dcb4](https://github.com/google/adk-python/commit/083dcb44650eb0e6b70219ede731f2fa78ea7d28))
* [Tools]Allow toolset to process llm_request before tools returned by it ([3643b4a](https://github.com/google/adk-python/commit/3643b4ae196fd9e38e52d5dc9d1cd43ea0733d36))
* [Tools]Support input/output schema by fully-qualified code reference ([dfee06a](https://github.com/google/adk-python/commit/dfee06ac067ea909251d6fb016f8331065d430e9))
* [Tools]Enhance LangchainTool to accept more forms of functions ([0ec69d0](https://github.com/google/adk-python/commit/0ec69d05a4016adb72abf9c94f2e9ff4bdd1848c))

### Bug Fixes

* **Attention**: Logging level for some API requests and responses was moved from `INFO` to `DEBUG` ([ff31f57](https://github.com/google/adk-python/commit/ff31f57dc95149f8f309f83f2ec983ef40f1122c))
  * Please set `--log_level=DEBUG`, if you are interested in having those API request and responses in logs.
* Add buffer to the write file option ([f2caf2e](https://github.com/google/adk-python/commit/f2caf2eecaf0336495fb42a2166b1b79e57d82d8))
* Allow current sub-agent to finish execution before exiting the loop agent due to a sub-agent's escalation. ([2aab1cf](https://github.com/google/adk-python/commit/2aab1cf98e1d0e8454764b549fac21475a633409))
* Check that `mean_score` is a valid float value ([65cb6d6](https://github.com/google/adk-python/commit/65cb6d6bf3278e6c3529938a7b932e3ef6d6c2ae))
* Handle non-json-serializable values in the `execute_sql` tool ([13ff009](https://github.com/google/adk-python/commit/13ff009d34836a80f107cb43a632df15f7c215e4))
* Raise `NotFoundError` in `list_eval_sets` function when app_name doesn't exist ([b17d8b6](https://github.com/google/adk-python/commit/b17d8b6e362a5b2a1b6a2dd0cff5e27a71c27925))
* Fixed serialization of tools with nested schema ([53df35e](https://github.com/google/adk-python/commit/53df35ee58599e9816bd4b9c42ff48457505e599))
* Set response schema for function tools that returns `None` ([33ac838](https://github.com/google/adk-python/commit/33ac8380adfff46ed8a7d518ae6f27345027c074))
* Support path level parameters for open_api_spec_parser ([6f01660](https://github.com/google/adk-python/commit/6f016609e889bb0947877f478de0c5729cfcd0c3))
* Use correct type for actions parameter in ApplicationIntegrationToolset ([ce7253f](https://github.com/google/adk-python/commit/ce7253f63ff8e78bccc7805bd84831f08990b881))
* Use the same word extractor for query and event contents in InMemoryMemoryService ([1c4c887](https://github.com/google/adk-python/commit/1c4c887bec9326aad2593f016540160d95d03f33))

### Documentation

* Fix missing toolbox-core dependency and improve installation guide ([2486349](https://github.com/google/adk-python/commit/24863492689f36e3c7370be40486555801858bac))


## 1.7.0 (2025-07-16)

### Features

* Add ability to send state change with message [3f9f773](https://github.com/google/adk-python/commit/3f9f773d9b5fcca343e32f76f6d5677b7cf4c327)
* [Eval] Support for persisting eval run results [bab3be2](https://github.com/google/adk-python/commit/bab3be2cf31dc9afd00bcce70103bdaa5460f1a3)
* Introduce [Plugin]: Plugin is simply a class that packages these individual callback functions together for a broader purpose[162228d](https://github.com/google/adk-python/commit/162228d208dca39550a75221030edf9876bf8e3a)

### Bug Fixes

* Create correct object for image and video content in litellm [bf7745f](https://github.com/google/adk-python/commit/bf7745f42811de3c9c80ec0998001ae50960dafc)
*  Support project-based gemini model path for BuiltInCodeExecutor and all built-in tools [a5d6f1e](https://github.com/google/adk-python/commit/a5d6f1e52ee36d84f94693086f74e4ca2d0bed65)
*  Add instruction in long running tool description to avoid being invoked again by model [62a6119](https://github.com/google/adk-python/commit/62a611956f8907e0580955adb23dfb6d7799bf4f)
*  [A2A] Import A2A well known path from A2A sdk [a6716a5](https://github.com/google/adk-python/commit/a6716a55140f63834ae4e3507b38786da9fdbee2)
*  Fix the long running function response event merge logic [134ec0d](https://github.com/google/adk-python/commit/134ec0d71e8de4cf9bcbe370c7e739e7ada123f3)
*  [A2A] Return final task result in task artifact instead of status message [a8fcc1b](https://github.com/google/adk-python/commit/a8fcc1b8ab0d47eccf6612a6eb8be021bff5ed3a)
* Make InMemoryMemoryService thread-safe [10197db](https://github.com/google/adk-python/commit/10197db0d752defc5976d1f276c7b5405a94c75b)

### Improvements

* Improve partial event handling and streaming aggregation [584c8c6](https://github.com/google/adk-python/commit/584c8c6d91308e62285c94629f020f2746e88f6f)

### Documentation

* Update agent transfer related doc string and comments [b1fa383](https://github.com/google/adk-python/commit/b1fa383e739d923399b3a23ca10435c0fba3460b)
* Update doc string for GcsArtifactService [498ce90](https://github.com/google/adk-python/commit/498ce906dd9b323b6277bc8118e1bcc68c38c1b5)

## [1.6.1](https://github.com/google/adk-python/compare/v1.5.0...v1.6.1) (2025-07-09)

### Features

* Add A2A support as experimental features [f0183a9](https://github.com/google/adk-python/commit/f0183a9b98b0bcf8aab4f948f467cef204ddc9d6)
  * Install google-adk with a2a extra: pip install google-adk[a2a]
  * Users can serve agents as A2A agent with `--a2a` option for `adk web` and
    `adk api_server`
  * Users can run a remote A2A agent with `RemoteA2AAgent` class
  * Three A2A agent samples are added:
    * contributing/samples/a2a_basic
    * contributing/samples/a2a_auth
    * contributing/samples/a2a_human_in_loop

* Support agent hot reload.[e545e5a](https://github.com/google/adk-python/commit/e545e5a570c1331d2ed8fda31c7244b5e0f71584)
  Users can add `--reload_agents` flag to `adk web` and `adk api_server` command
  to reload agents automatically when new changes are detected.

* Eval features
  * Implement auto rater-based evaluator for responses [75699fb](https://github.com/google/adk-python/commit/75699fbeca06f99c6f2415938da73bb423ec9b9b)
  * Add Safety evaluator metric [0bd05df](https://github.com/google/adk-python/commit/0bd05df471a440159a44b5864be4740b0f1565f9)
  * Add BaseEvalService declaration and surrounding data models [b0d88bf](https://github.com/google/adk-python/commit/b0d88bf17242e738bcd409b3d106deed8ce4d407)

* Minor features
  * Add `custom_metadata` to VertexAiSessionService when adding events [a021222](https://github.com/google/adk-python/commit/a02122207734cabb26f7c23e84d2336c4b8b0375)
  * Support protected write in BigQuery `execute_sql` tool [dc43d51](https://github.com/google/adk-python/commit/dc43d518c90b44932b3fdedd33fca9e6c87704e2)
  * Added clone() method to BaseAgent to allow users to create copies of an agent [d263afd] (https://github.com/google/adk-python/commit/d263afd91ba4a3444e5321c0e1801c499dec4c68)

### Bug Fixes

* Support project-based gemini model path to use enterprise_web_search_tool [e33161b](https://github.com/google/adk-python/commit/e33161b4f8650e8bcb36c650c4e2d1fe79ae2526)
* Use inspect.signature() instead of typing.get_type_hints for examining function signatures[4ca77bc](https://github.com/google/adk-python/commit/4ca77bc056daa575621a80d3c8d5014b78209233)
* Replace Event ID generation with UUID4 to prevent SQLite integrity constraint failures [e437c7a](https://github.com/google/adk-python/commit/e437c7aac650ac6a53fcfa71bd740e3e5ec0f230)
* Remove duplicate options from `adk deploy` [3fa2ea7](https://github.com/google/adk-python/commit/3fa2ea7cb923c9f8606d98b45a23bd58a7027436)
* Fix scenario where a user can access another users events given the same session id [362fb3f](https://github.com/google/adk-python/commit/362fb3f2b7ac4ad15852d00ce4f3935249d097f6)
* Handle unexpected 'parameters' argument in FunctionTool.run_async [0959b06](https://github.com/google/adk-python/commit/0959b06dbdf3037fe4121f12b6d25edca8fb9afc)
* Make sure each partial event has different timestamp [17d6042](https://github.com/google/adk-python/commit/17d604299505c448fcb55268f0cbaeb6c4fa314a)
* Avoid pydantic.ValidationError when the model stream returns empty final chunk [9b75e24](https://github.com/google/adk-python/commit/9b75e24d8c01878c153fec26ccfea4490417d23b)
* Fix google_search_tool.py to support updated Gemini LIVE model naming [77b869f](https://github.com/google/adk-python/commit/77b869f5e35a66682cba35563824fd23a9028d7c)
* Adding detailed information on each metric evaluation [04de3e1](https://github.com/google/adk-python/commit/04de3e197d7a57935488eb7bfa647c7ab62cd9d9)
* Converts litellm generate config err [3901fad](https://github.com/google/adk-python/commit/3901fade71486a1e9677fe74a120c3f08efe9d9e)
* Save output in state via output_key only when the event is authored by current agent [20279d9](https://github.com/google/adk-python/commit/20279d9a50ac051359d791dea77865c17c0bbf9e)
* Treat SQLite database update time as UTC for session's last update time [3f621ae](https://github.com/google/adk-python/commit/3f621ae6f2a5fac7f992d3d833a5311b4d4e7091)
* Raise ValueError when sessionId and userId are incorrect combination(#1653) [4e765ae](https://github.com/google/adk-python/commit/4e765ae2f3821318e581c26a52e11d392aaf72a4)
* Support API-Key for MCP Tool authentication [045aea9](https://github.com/google/adk-python/commit/045aea9b15ad0190a960f064d6e1e1fc7f964c69)
* Lock LangGraph version to <= 0.4.10 [9029b8a](https://github.com/google/adk-python/commit/9029b8a66e9d5e0d29d9a6df0e5590cc7c0e9038)
* Update the retry logic of create session polling [3d2f13c](https://github.com/google/adk-python/commit/3d2f13cecd3fef5adfa1c98bf23d7b68ff355f4d)

### Chores

* Extract mcp client creation logic to a separate method [45d60a1](https://github.com/google/adk-python/commit/45d60a1906bfe7c43df376a829377e2112ea3d17)
* Add tests for live streaming configs [bf39c00](https://github.com/google/adk-python/commit/bf39c006102ef3f01e762e7bb744596a4589f171)
* Update ResponseEvaluator to use newer version of Eval SDK [62c4a85](https://github.com/google/adk-python/commit/62c4a8591780a9a3fdb03a0de11092d84118a1b9)
* Add util to build our llms.txt and llms-full.txt files [a903c54](https://github.com/google/adk-python/commit/a903c54bacfcb150dc315bec9c67bf7ce9551c07)
* Create an example for multi agent live streaming [a58cc3d](https://github.com/google/adk-python/commit/a58cc3d882e59358553e8ea16d166b1ab6d3aa71)
* Refactor the ADK Triaging Agent to make the code easier to read [b6c7b5b](https://github.com/google/adk-python/commit/b6c7b5b64fcd2e83ed43f7b96ea43791733955d8)


### Documentation

* Update the a2a exmaple link in README.md [d0fdfb8](https://github.com/google/adk-python/commit/d0fdfb8c8e2e32801999c81de8d8ed0be3f88e76)
* Adds AGENTS.md to provide relevant project context for the Gemini CLI [37108be](https://github.com/google/adk-python/commit/37108be8557e011f321de76683835448213f8515)
* Update CONTRIBUTING.md [ffa9b36](https://github.com/google/adk-python/commit/ffa9b361db615ae365ba62c09a8f4226fb761551)
* Add adk project overview and architecture [28d0ea8](https://github.com/google/adk-python/commit/28d0ea876f2f8de952f1eccbc788e98e39f50cf5)
* Add docstring to clarify that inmemory service are not suitable for production [dc414cb](https://github.com/google/adk-python/commit/dc414cb5078326b8c582b3b9072cbda748766286)
* Update agents.md to include versioning strategy [6a39c85](https://github.com/google/adk-python/commit/6a39c854e032bda3bc15f0e4fe159b41cf2f474b)
* Add tenacity into project.toml [df141db](https://github.com/google/adk-python/commit/df141db60c1137a6bcddd6d46aad3dc506868543)
* Updating CONTRIBUTING.md with missing extra [e153d07](https://github.com/google/adk-python/commit/e153d075939fb628a7dc42b12e1b3461842db541)

## [1.5.0](https://github.com/google/adk-python/compare/v1.4.2...v1.5.0) (2025-06-25)


### Features

* Add a new option `eval_storage_uri` in adk web & adk eval to specify GCS bucket to store eval data ([fa025d7](https://github.com/google/adk-python/commit/fa025d755978e1506fa0da1fecc49775bebc1045))
* Add ADK examples for litellm with add_function_to_prompt ([f33e090](https://github.com/google/adk-python/commit/f33e0903b21b752168db3006dd034d7d43f7e84d))
* Add implementation of VertexAiMemoryBankService and support in FastAPI endpoint ([abc89d2](https://github.com/google/adk-python/commit/abc89d2c811ba00805f81b27a3a07d56bdf55a0b))
* Add rouge_score library to ADK eval dependencies, and implement RougeEvaluator that is computes ROUGE-1 for "response_match_score" metric ([9597a44](https://github.com/google/adk-python/commit/9597a446fdec63ad9e4c2692d6966b14f80ff8e2))
* Add usage span attributes to telemetry ([#356](https://github.com/google/adk-python/issues/356)) ([ea69c90](https://github.com/google/adk-python/commit/ea69c9093a16489afdf72657136c96f61c69cafd))
* Add Vertex Express mode compatibility for VertexAiSessionService ([00cc8cd](https://github.com/google/adk-python/commit/00cc8cd6433fc45ecfc2dbaa04dbbc1a81213b4d))


### Bug Fixes

* Include current turn context when include_contents='none' ([9e473e0](https://github.com/google/adk-python/commit/9e473e0abdded24e710fd857782356c15d04b515))
* Make LiteLLM streaming truly asynchronous ([bd67e84](https://github.com/google/adk-python/commit/bd67e8480f6e8b4b0f8c22b94f15a8cda1336339))
* Make raw_auth_credential and exchanged_auth_credential optional given their default value is None ([acbdca0](https://github.com/google/adk-python/commit/acbdca0d8400e292ba5525931175e0d6feab15f1))
* Minor typo fix in the agent instruction ([ef3c745](https://github.com/google/adk-python/commit/ef3c745d655538ebd1ed735671be615f842341a8))
* Typo fix in sample agent instruction ([ef3c745](https://github.com/google/adk-python/commit/ef3c745d655538ebd1ed735671be615f842341a8))
* Update contributing links ([a1e1441](https://github.com/google/adk-python/commit/a1e14411159fd9f3e114e15b39b4949d0fd6ecb1))
* Use starred tuple unpacking on GCS artifact blob names ([3b1d9a8](https://github.com/google/adk-python/commit/3b1d9a8a3e631ca2d86d30f09640497f1728986c))


### Chore

* Do not send api request when session does not have events ([88a4402](https://github.com/google/adk-python/commit/88a4402d142672171d0a8ceae74671f47fa14289))
* Leverage official uv action for install([09f1269](https://github.com/google/adk-python/commit/09f1269bf7fa46ab4b9324e7f92b4f70ffc923e5))
* Update google-genai package and related deps to latest([ed7a21e](https://github.com/google/adk-python/commit/ed7a21e1890466fcdf04f7025775305dc71f603d))
* Add credential service backed by session state([29cd183](https://github.com/google/adk-python/commit/29cd183aa1b47dc4f5d8afe22f410f8546634abc))
* Clarify the behavior of Event.invocation_id([f033e40](https://github.com/google/adk-python/commit/f033e405c10ff8d86550d1419a9d63c0099182f9))
* Send user message to the agent that returned a corresponding function call if user message is a function response([7c670f6](https://github.com/google/adk-python/commit/7c670f638bc17374ceb08740bdd057e55c9c2e12))
* Add request converter to convert a2a request to ADK request([fb13963](https://github.com/google/adk-python/commit/fb13963deda0ff0650ac27771711ea0411474bf5))
* Support allow_origins in cloud_run deployment ([2fd8feb](https://github.com/google/adk-python/commit/2fd8feb65d6ae59732fb3ec0652d5650f47132cc))

## [1.4.2](https://github.com/google/adk-python/compare/v1.4.1...v1.4.2) (2025-06-20)


### Bug Fixes

* Add type checking to handle different response type of genai API client ([4d72d31](https://github.com/google/adk-python/commit/4d72d31b13f352245baa72b78502206dcbe25406))
  * This fixes the broken VertexAiSessionService
* Allow more credentials types for BigQuery tools ([2f716ad](https://github.com/google/adk-python/commit/2f716ada7fbcf8e03ff5ae16ce26a80ca6fd7bf6))

## [1.4.1](https://github.com/google/adk-python/compare/v1.3.0...v1.4.1) (2025-06-18)


### Features

* Add Authenticated Tool (Experimental) ([dcea776](https://github.com/google/adk-python/commit/dcea7767c67c7edfb694304df32dca10b74c9a71))
* Add enable_affective_dialog and proactivity to run_config and llm_request ([fe1d5aa](https://github.com/google/adk-python/commit/fe1d5aa439cc56b89d248a52556c0a9b4cbd15e4))
* Add import session API in the fast API ([233fd20](https://github.com/google/adk-python/commit/233fd2024346abd7f89a16c444de0cf26da5c1a1))
* Add integration tests for litellm with and without turning on add_function_to_prompt ([8e28587](https://github.com/google/adk-python/commit/8e285874da7f5188ea228eb4d7262dbb33b1ae6f))
* Allow data_store_specs pass into ADK VAIS built-in tool ([675faef](https://github.com/google/adk-python/commit/675faefc670b5cd41991939fe0fc604df331111a))
* Enable MCP Tool Auth (Experimental) ([157d9be](https://github.com/google/adk-python/commit/157d9be88d92f22320604832e5a334a6eb81e4af))
* Implement GcsEvalSetResultsManager to handle storage of eval sets on GCS, and refactor eval set results manager ([0a5cf45](https://github.com/google/adk-python/commit/0a5cf45a75aca7b0322136b65ca5504a0c3c7362))
* Re-factor some eval sets manager logic, and implement GcsEvalSetsManager to handle storage of eval sets on GCS ([1551bd4](https://github.com/google/adk-python/commit/1551bd4f4d7042fffb497d9308b05f92d45d818f))
* Support real time input config ([d22920b](https://github.com/google/adk-python/commit/d22920bd7f827461afd649601326b0c58aea6716))
* Support refresh access token automatically for rest_api_tool ([1779801](https://github.com/google/adk-python/commit/177980106b2f7be9a8c0a02f395ff0f85faa0c5a))

### Bug Fixes

* Fix Agent generate config err ([#1305](https://github.com/google/adk-python/issues/1305)) ([badbcbd](https://github.com/google/adk-python/commit/badbcbd7a464e6b323cf3164d2bcd4e27cbc057f))
* Fix Agent generate config error ([#1450](https://github.com/google/adk-python/issues/1450)) ([694b712](https://github.com/google/adk-python/commit/694b71256c631d44bb4c4488279ea91d82f43e26))
* Fix liteLLM test failures ([fef8778](https://github.com/google/adk-python/commit/fef87784297b806914de307f48c51d83f977298f))
* Fix tracing for live ([58e07ca](https://github.com/google/adk-python/commit/58e07cae83048d5213d822be5197a96be9ce2950))
* Merge custom http options with adk specific http options in model api request ([4ccda99](https://github.com/google/adk-python/commit/4ccda99e8ec7aa715399b4b83c3f101c299a95e8))
* Remove unnecessary double quote on Claude docstring ([bbceb4f](https://github.com/google/adk-python/commit/bbceb4f2e89f720533b99cf356c532024a120dc4))
* Set explicit project in the BigQuery client ([6d174eb](https://github.com/google/adk-python/commit/6d174eba305a51fcf2122c0fd481378752d690ef))
* Support streaming in litellm + adk and add corresponding integration tests ([aafa80b](https://github.com/google/adk-python/commit/aafa80bd85a49fb1c1a255ac797587cffd3fa567))
* Support project-based gemini model path to use google_search_tool ([b2fc774](https://github.com/google/adk-python/commit/b2fc7740b363a4e33ec99c7377f396f5cee40b5a))
* Update conversion between Celsius and Fahrenheit ([1ae176a](https://github.com/google/adk-python/commit/1ae176ad2fa2b691714ac979aec21f1cf7d35e45))

### Chores

* Set `agent_engine_id` in the VertexAiSessionService constructor, also use the `agent_engine_id` field instead of overriding `app_name` in FastAPI endpoint ([fc65873](https://github.com/google/adk-python/commit/fc65873d7c31be607f6cd6690f142a031631582a))



## [1.3.0](https://github.com/google/adk-python/compare/v1.2.1...v1.3.0) (2025-06-11)


### Features

* Add memory_service option to CLI ([416dc6f](https://github.com/google/adk-python/commit/416dc6feed26e55586d28f8c5132b31413834c88))
* Add support for display_name and description when deploying to agent engine ([aaf1f9b](https://github.com/google/adk-python/commit/aaf1f9b930d12657bfc9b9d0abd8e2248c1fc469))
* Dev UI: Trace View
  * New trace tab which contains all traces grouped by user messages
  * Click each row will open corresponding event details
  * Hover each row will highlight the corresponding message in dialog
* Dev UI: Evaluation
  * Evaluation Configuration: users can now configure custom threshold for the metrics used for each eval run ([d1b0587](https://github.com/google/adk-python/commit/d1b058707eed72fd4987d8ec8f3b47941a9f7d64))
  * Each eval case added can now be viewed and edited. Right now we only support edit of text.
  * Show the used metric in evaluation history ([6ed6351](https://github.com/google/adk-python/commit/6ed635190c86d5b2ba0409064cf7bcd797fd08da))
* Tool enhancements:
  * Add url_context_tool ([fe1de7b](https://github.com/google/adk-python/commit/fe1de7b10326a38e0d5943d7002ac7889c161826))
  * Support to customize timeout for mcpstdio connections ([54367dc](https://github.com/google/adk-python/commit/54367dcc567a2b00e80368ea753a4fc0550e5b57))
  * Introduce write protected mode to BigQuery tools ([6c999ca](https://github.com/google/adk-python/commit/6c999caa41dca3a6ec146ea42b0a794b14238ec2))



### Bug Fixes

* Agent Engine deployment:
  * Correct help text formatting for `adk deploy agent_engine` ([13f98c3](https://github.com/google/adk-python/commit/13f98c396a2fa21747e455bb5eed503a553b5b22))
  * Handle project and location in the .env properly when deploying to Agent Engine ([0c40542](https://github.com/google/adk-python/commit/0c4054200fd50041f0dce4b1c8e56292b99a8ea8))
* Fix broken agent graphs ([3b1f2ae](https://github.com/google/adk-python/commit/3b1f2ae9bfdb632b52e6460fc5b7c9e04748bd50))
* Forward `__annotations__` to the fake func for FunctionTool inspection ([9abb841](https://github.com/google/adk-python/commit/9abb8414da1055ab2f130194b986803779cd5cc5))
* Handle the case when agent loading error doesn't have msg attribute in agent loader ([c224626](https://github.com/google/adk-python/commit/c224626ae189d02e5c410959b3631f6bd4d4d5c1))
* Prevent agent_graph.py throwing when workflow agent is root agent ([4b1c218](https://github.com/google/adk-python/commit/4b1c218cbe69f7fb309b5a223aa2487b7c196038))
* Remove display_name for non-Vertex file uploads ([cf5d701](https://github.com/google/adk-python/commit/cf5d7016a0a6ccf2b522df6f2d608774803b6be4))


### Documentation

* Add DeepWiki badge to README ([f38c08b](https://github.com/google/adk-python/commit/f38c08b3057b081859178d44fa2832bed46561a9))
* Update code example in tool declaration to reflect BigQuery artifact description ([3ae6ce1](https://github.com/google/adk-python/commit/3ae6ce10bc5a120c48d84045328c5d78f6eb85d4))


## [1.2.1](https://github.com/google/adk-python/compare/v1.2.0...v1.2.1) (2025-06-04)


### Bug Fixes

* Import deprecated from typing_extensions ([068df04](https://github.com/google/adk-python/commit/068df04bcef694725dd36e09f4476b5e67f1b456))


## [1.2.0](https://github.com/google/adk-python/compare/v1.1.1...v1.2.0) (2025-06-04)


### Features

* Add agent engine as a deployment option to the ADK CLI ([2409c3e](https://github.com/google/adk-python/commit/2409c3ef192262c80f5328121f6dc4f34265f5cf))
* Add an option to use gcs artifact service in adk web. ([8d36dbd](https://github.com/google/adk-python/commit/8d36dbda520b1c0dec148e1e1d84e36ddcb9cb95))
* Add index tracking to handle parallel tool call using litellm ([05f4834](https://github.com/google/adk-python/commit/05f4834759c9b1f0c0af9d89adb7b81ea67d82c8))
* Add sortByColumn functionality to List Operation ([af95dd2](https://github.com/google/adk-python/commit/af95dd29325865ec30a1945b98e65e457760e003))
* Add implementation for  `get_eval_case`, `update_eval_case` and `delete_eval_case` for the local eval sets manager. ([a7575e0](https://github.com/google/adk-python/commit/a7575e078a564af6db3f42f650e94ebc4f338918))
* Expose more config of VertexAiSearchTool from latest Google GenAI SDK ([2b5c89b](https://github.com/google/adk-python/commit/2b5c89b3a94e82ea4a40363ea8de33d9473d7cf0))
* New Agent Visualization ([da4bc0e](https://github.com/google/adk-python/commit/da4bc0efc0dd96096724559008205854e97c3fd1))
* Set the max width and height of view image dialog to be 90% ([98a635a](https://github.com/google/adk-python/commit/98a635afee399f64e0a813d681cd8521fbb49500))
* Support Langchain StructuredTool for Langchain tool ([7e637d3](https://github.com/google/adk-python/commit/7e637d3fa05ca3e43a937e7158008d2b146b1b81))
* Support Langchain tools that has run_manager in _run args and don't have args_schema populated ([3616bb5](https://github.com/google/adk-python/commit/3616bb5fc4da90e79eb89039fb5e302d6a0a14ec))
* Update for anthropic models ([16f7d98](https://github.com/google/adk-python/commit/16f7d98acf039f21ec8a99f19eabf0ef4cb5268c))
* Use bigquery scope by default in bigquery credentials. ([ba5b80d](https://github.com/google/adk-python/commit/ba5b80d5d774ff5fdb61bd43b7849057da2b4edf))
* Add jira_agent adk samples code which connect Jira cloud ([8759a25](https://github.com/google/adk-python/commit/8759a2525170edb2f4be44236fa646a93ba863e6))
* Render HTML artifact in chat window ([5c2ad32](https://github.com/google/adk-python/commit/5c2ad327bf4262257c3bc91010c3f8c303d3a5f5))
* Add export to json button in the chat window ([fc3e374](https://github.com/google/adk-python/commit/fc3e374c86c4de87b4935ee9c56b6259f00e8ea2))
* Add tooltip to the export session button ([2735942](https://github.com/google/adk-python/commit/273594215efe9dbed44d4ef85e6234bd7ba7b7ae))


### Bug Fixes

* Add adk icon for UI ([2623c71](https://github.com/google/adk-python/commit/2623c710868d832b6d5119f38e22d82adb3de66b))
* Add cache_ok option to remove sa warning. ([841e10a](https://github.com/google/adk-python/commit/841e10ae353e0b1b3d020a26d6cac6f37981550e))
* Add support for running python main function in UnsafeLocalCodeExecutor when the code has an if __name__ == "__main__" statement. ([95e33ba](https://github.com/google/adk-python/commit/95e33baf57e9c267a758e08108cde76adf8af69b))
* Adk web not working on some env for windows, fixes https://github.com/google/adk-web/issues/34 ([daac8ce](https://github.com/google/adk-python/commit/daac8cedfe6d894f77ea52784f0a6d19003b2c00))
* Assign empty inputSchema to MCP tool when converting an ADK tool that wraps a function which takes no parameters. ([2a65c41](https://github.com/google/adk-python/commit/2a65c4118bb2aa97f2a13064db884bd63c14a5f7))
* Call all tools in parallel calls during partial authentication ([0e72efb](https://github.com/google/adk-python/commit/0e72efb4398ce6a5d782bcdcb770b2473eb5af2e))
* Continue fetching events if there are multiple pages. ([6506302](https://github.com/google/adk-python/commit/65063023a5a7cb6cd5db43db14a411213dc8acf5))
* Do not convert "false" value to dict ([60ceea7](https://github.com/google/adk-python/commit/60ceea72bde2143eb102c60cf33b365e1ab07d8f))
* Enhance agent loader exception handler and expose precise error information ([7b51ae9](https://github.com/google/adk-python/commit/7b51ae97245f6990c089183734aad41fe59b3330))
* Ensure function description is copied when ignoring parameters ([7fdc6b4](https://github.com/google/adk-python/commit/7fdc6b4417e5cf0fbc72d3117531914353d3984a))
* Filter memory by app_name and user_id. ([db4bc98](https://github.com/google/adk-python/commit/db4bc9809c7bb6b0d261973ca7cfd87b392694be))
* Fix filtering by user_id for vertex ai session service listing ([9d4ca4e](https://github.com/google/adk-python/commit/9d4ca4ed44cf10bc87f577873faa49af469acc25))
* fix parameter schema generation for gemini ([5a67a94](https://github.com/google/adk-python/commit/5a67a946d2168b80dd6eba008218468c2db2e74e))
* Handle non-indexed function call chunks with incremental fallback index ([b181cbc](https://github.com/google/adk-python/commit/b181cbc8bc629d1c9bfd50054e47a0a1b04f7410))
* Handles function tool parsing corner case where type hints are stored as strings. ([a8a2074](https://github.com/google/adk-python/commit/a8a20743f92cd63c3d287a3d503c1913dd5ad5ae))
* Introduce PreciseTimestamp to fix mysql datetime precision issue. ([841e10a](https://github.com/google/adk-python/commit/841e10ae353e0b1b3d020a26d6cac6f37981550e))
* match arg case in errors ([b226a06](https://github.com/google/adk-python/commit/b226a06c0bf798f85a53c591ad12ee582703af6d))
* ParallelAgent should only append to its immediate sub-agent, not transitive descendants ([ec8bc73](https://github.com/google/adk-python/commit/ec8bc7387c84c3f261c44cedfe76eb1f702e7b17))
* Relax openapi spec to gemini schema conversion to tolerate more cases ([b1a74d0](https://github.com/google/adk-python/commit/b1a74d099fae44d41750b79e58455282d919dd78))
* Remove labels from config when using API key from Google AI Studio to call model ([5d29716](https://github.com/google/adk-python/commit/5d297169d08a2d0ea1a07641da2ac39fa46b68a4))
* **sample:** Correct text artifact saving in artifact_save_text sample ([5c6001d](https://github.com/google/adk-python/commit/5c6001d90fe6e1d15a2db6b30ecf9e7b6c26eee4))
* Separate thinking from text parts in streaming mode ([795605a](https://github.com/google/adk-python/commit/795605a37e1141e37d86c9b3fa484a3a03e7e9a6))
* Simplify content for ollama provider ([eaee49b](https://github.com/google/adk-python/commit/eaee49bc897c20231ecacde6855cccfa5e80d849))
* Timeout issues for mcpstdio server when mcp tools are incorrect. ([45ef668](https://github.com/google/adk-python/commit/45ef6684352e3c8082958bece8610df60048f4a3))
* **transfer_to_agent:** update docstring for clarity and accuracy ([854a544](https://github.com/google/adk-python/commit/854a5440614590c2a3466cf652688ba57d637205))
* Update unit test code for test_connection ([b0403b2](https://github.com/google/adk-python/commit/b0403b2d98b2776d15475f6b525409670e2841fc))
* Use inspect.cleandoc on function docstrings in generate_function_declaration. ([f7cb666](https://github.com/google/adk-python/commit/f7cb66620be843b8d9f3d197d6e8988e9ee0dfca))
* Restore errors path ([32c5ffa](https://github.com/google/adk-python/commit/32c5ffa8ca5e037f41ff345f9eecf5b26f926ea1))
* Unused import for deprecated ([ccd05e0](https://github.com/google/adk-python/commit/ccd05e0b00d0327186e3b1156f1b0216293efe21))
* Prevent JSON parsing errors and preserve non-ascii characters in telemetry ([d587270](https://github.com/google/adk-python/commit/d587270327a8de9f33b3268de5811ac756959850))
* Raise HTTPException when running evals in fast_api if google-adk[eval] is not installed ([1de5c34](https://github.com/google/adk-python/commit/1de5c340d8da1cedee223f6f5a8c90070a9f0298))
* Fix typos in README for sample bigquery_agent and oauth_calendar_agent ([9bdd813](https://github.com/google/adk-python/commit/9bdd813be15935af5c5d2a6982a2391a640cab23))
* Make tool_call one span for telemetry and renamed to execute_tool ([999a7fe](https://github.com/google/adk-python/commit/999a7fe69d511b1401b295d23ab3c2f40bccdc6f))
* Use media type in chat window. Remove isArtifactImage and isArtifactAudio reference ([1452dac](https://github.com/google/adk-python/commit/1452dacfeb6b9970284e1ddeee6c4f3cb56781f8))
* Set output_schema correctly for LiteLllm ([6157db7](https://github.com/google/adk-python/commit/6157db77f2fba4a44d075b51c83bff844027a147))
* Update pending event dialog style ([1db601c](https://github.com/google/adk-python/commit/1db601c4bd90467b97a2f26fe9d90d665eb3c740))
* Remove the gap between event holder and image ([63822c3](https://github.com/google/adk-python/commit/63822c3fa8b0bdce2527bd0d909c038e2b66dd98))


### Documentation

* Adds a sample agent to illustrate state usage via `callbacks`. ([18fbe3c](https://github.com/google/adk-python/commit/18fbe3cbfc9f2af97e4b744ec0a7552331b1d8e3))
* Fix typos in documentation ([7aaf811](https://github.com/google/adk-python/commit/7aaf8116169c210ceda35c649b5b49fb65bbb740))
* Change eval_dataset to eval_dataset_file_path_or_dir ([62d7bf5](https://github.com/google/adk-python/commit/62d7bf58bb1c874caaf3c56a614500ae3b52f215))
* Fix broken link to A2A example ([0d66a78](https://github.com/google/adk-python/commit/0d66a7888b68380241b92f7de394a06df5a0cc06))
* Fix typo in envs.py ([bd588bc](https://github.com/google/adk-python/commit/bd588bce50ccd0e70b96c7291db035a327ad4d24))
* Updates CONTRIBUTING.md to refine setup process using uv. ([04e07b4](https://github.com/google/adk-python/commit/04e07b4a1451123272641a256c6af1528ea6523e))
* Create and update project documentation including README.md and CONTRIBUTING.md ([f180331](https://github.com/google/adk-python/commit/f1803312c6a046f94c23cfeaed3e8656afccf7c3))
* Rename the root agent in the example to match the example name ([94c0aca](https://github.com/google/adk-python/commit/94c0aca685f1dfa4edb44caaedc2de25cc0caa41))
* ADK: add section comment ([349a414](https://github.com/google/adk-python/commit/349a414120fbff0937966af95864bd683f063d08))


### Chore

* Miscellaneous changes ([0724a83](https://github.com/google/adk-python/commit/0724a83aa9cda00c1b228ed47a5baa7527bb4a0a), [a9dcc58](https://github.com/google/adk-python/commit/a9dcc588ad63013d063dbe37095c0d2e870142c3), [ac52eab](https://github.com/google/adk-python/commit/ac52eab88eccafa451be7584e24aea93ff15f3f3), [a0714b8](https://github.com/google/adk-python/commit/a0714b8afc55461f315ede8451b17aad18d698dd))
* Enable release-please workflow ([57d99aa](https://github.com/google/adk-python/commit/57d99aa7897fb229f41c2a08034606df1e1e6064))
* Added unit test coverage for local_eval_sets_manager.py ([174afb3](https://github.com/google/adk-python/commit/174afb3975bdc7e5f10c26f3eebb17d2efa0dd59))
* Extract common options for `adk web` and `adk api_server` ([01965bd](https://github.com/google/adk-python/commit/01965bdd74a9dbdb0ce91a924db8dee5961478b8))

## 1.1.1

### Features
* Add BigQuery first-party tools. See [here](https://github.com/google/adk-python/commit/d6c6bb4b2489a8b7a4713e4747c30d6df0c07961) for more details.


## 1.1.0

### Features

* Extract agent loading logic from fast_api.py to a separate AgentLoader class and support more agent definition folder/file structure.
* Added audio play in web UI.
* Added input transcription support for live/streaming.
* Added support for storing eval run history locally in adk eval cli.
* Image artifacts can now be clicked directly in chat message to view.
* Left side panel can now be resized.

### Bug Fixes

* Avoid duplicating log in stderr.
* Align event filtering and ordering logic.
* Add handling for None param.annotation.
* Fixed several minor bugs regarding eval tab in web UI.

### Miscellaneous Chores

* Updates mypy config in pyproject.toml.
* Add google search agent in samples.
* Update filtered schema parameters for Gemini API.
* Adds autoformat.sh for formatting codebase.

## 1.0.0

### ⚠ BREAKING CHANGES

* Evaluation dataset schema is finalized with strong-type pydantic models.
  (previously saved eval file needs re-generation, for both adk eval cli and
  the eval tab in adk web UI).
* `BuiltInCodeExecutor` (in code_executors package) replaces
  `BuiltInCodeExecutionTool` (previously in tools package).
* All methods in services are now async, including session service, artifact
  service and memory service.
  * `list_events` and `close_session` methods are removed from session service.
* agent.py file structure with MCP tools are now easier and simpler ([now](https://github.com/google/adk-python/blob/3b5232c14f48e1d5b170f3698d91639b079722c8/contributing/samples/mcp_stdio_server_agent/agent.py#L33) vs [before](https://github.com/google/adk-python/blob/a4adb739c0d86b9ae4587547d2653d568f6567f2/contributing/samples/mcp_agent/agent.py#L41)).
  Old format is not working anymore.
* `Memory` schema and `MemoryService` is redesigned.
* Mark various class attributes as private in the classes in the `tools` package.
* Disabled session state injection if instruction provider is used.
  (so that you can have `{var_name}` in the instruction, which is required for code snippets)
* Toolbox integration is revamped: tools/toolbox_tool.py → tools/toolbox_toolset.py.
* Removes the experimental `remote_agent.py`. We'll redesign it and bring it back.

### Features

* Dev UI:
  * A brand new trace view for overall agent invocation.
  * A revamped evaluation tab and comparison view for checking eval results.
* Introduced `BaseToolset` to allow dynamically add/remove tools for agents.
  * Revamped MCPToolset with the new BaseToolset interface.
  * Revamped GoogleApiTool, GoogleApiToolset and ApplicationIntegrationToolset with the new BaseToolset interface.
  * Resigned agent.py file structure when needing MCPToolset.
  * Added ToolboxToolset.
* Redesigned strong-typed agent evaluation schema.
  * Allows users to create more cohesive eval sets.
  * Allows evals to be extended for non-text modality.
  * Allows for a structured interaction with the uber eval system.
* Redesigned Memory schema and MemoryService interfaces.
* Added token usage to LlmResponse.
* Allowed specifying `--adk_version` in `adk deploy cloud_run` cli. Default is the current version.

### Bug Fixes

* Fixed `adk deploy cloud_run` failing bug.
* Fixed logs not being printed due to `google-auth` library.

### Miscellaneous Chores

* Display full help text when adk cli receives invalid arguments.
* `adk web` now binds `127.0.0.1` by default, instead of 0.0.0.0.
* `InMemoryRunner` now takes `BaseAgent` in constructor.
* Various docstring improvements.
* Various UI tweaks.
* Various bug fixes.
* Update various contributing/samples for contributors to validate the implementation.


## 0.5.0

### ⚠ BREAKING CHANGES

* Updated artifact and memory service interface to be async. Agents that
  interact with these services through callbacks or tools will now need to
  adjust their invocation methods to be async (using await), or ensure calls
  are wrapped in an asynchronous executor like asyncio.run(). Any service that
  extends the base interface must also be updated.

### Features

* Introduced the ability to chain model callbacks.
* Added support for async agent and model callbacks.
* Added input transcription support for live/streaming.
* Captured all agent code error and display on UI.
* Set param required tag to False by default in openapi_tool.
* Updated evaluation functions to be asynchronous.

### Bug Fixes

* Ensured a unique ID is generated for every event.
* Fixed the issue when openapi_specparser has parameter.required as None.
* Updated the 'type' value on the items/properties nested structures for Anthropic models to adhere to JSON schema.
* Fix litellm error issues.

### Miscellaneous Chores

* Regenerated API docs.
* Created a `developer` folder and added samples.
* Updated the contributing guide.
* Docstring improvements, typo fixings, GitHub action to enforce code styles on formatting and imports, etc.

## 0.4.0

### ⚠ BREAKING CHANGES
* Set the max size of strings in database columns. MySQL mandates that all VARCHAR-type fields must specify their lengths.
* Extract content encode/decode logic to a shared util, resolve issues with JSON serialization, and update key length for DB table to avoid key too long issue in mysql.
* Enhance `FunctionTool` to verify if the model is providing all the mandatory arguments.

### Features
* Update ADK setup guide to improve onboarding experience.
* feat: add ordering to recent events in database session service.
* feat(llm_flows): support async before/after tool callbacks.
* feat: Added --replay and --resume options to adk run cli. Check adk run --help for more details.
* Created a new Integration Connector Tool (underlying of the ApplicationIntegrationToolSet) so that we do not force LLM to provide default value.

### Bug Fixes

* Don't send content with empty text to LLM.
* Fix google search reading undefined for `renderedContent`.

### Miscellaneous Chores
* Docstring improvements, typo fixings, github action to enfore code styles on formatting and imports, etc.

## 0.3.0

### ⚠ BREAKING CHANGES

* Auth: expose `access_token` and `refresh_token` at top level of auth
  credentials, instead of a `dict`
  ([commit](https://github.com/google/adk-python/commit/956fb912e8851b139668b1ccb8db10fd252a6990)).

### Features

* Added support for running agents with MCPToolset easily on `adk web`.
* Added `custom_metadata` field to `LlmResponse`, which can be used to tag
  LlmResponse via `after_model_callback`.
* Added `--session_db_url` to `adk deploy cloud_run` option.
* Many Dev UI improvements:
  * Better google search result rendering.
  * Show websocket close reason in Dev UI.
  * Better error message showing for audio/video.

### Bug Fixes

* Fixed MCP tool json schema parsing issue.
* Fixed issues in DatabaseSessionService that leads to crash.
* Fixed functions.py.
* Fixed `skip_summarization` behavior in `AgentTool`.

### Miscellaneous Chores

* README.md improvements.
* Various code improvements.
* Various typo fixes.
* Bump min version of google-genai to 1.11.0.

## 0.2.0

### ⚠ BREAKING CHANGES

* Fix typo in method name in `Event`: has_trailing_code_exeuction_result --> has_trailing_code_execution_result.

### Features

* `adk` CLI:
  * Introduce `adk create` cli tool to help creating agents.
  * Adds `--verbosity` option to `adk deploy cloud_run` to show detailed cloud
    run deploy logging.
* Improve the initialization error message for `DatabaseSessionService`.
* Lazy loading for Google 1P tools to minimize the initial latency.
* Support emitting state-change-only events from planners.
* Lots of Dev UI updates, including:
  * Show planner thoughts and actions in the Dev UI.
  * Support MCP tools in Dev UI.
    (NOTE: `agent.py` interface is temp solution and is subject to change)
  * Auto-select the only app if only one app is available.
  * Show grounding links generated by Google Search Tool.
* `.env` file is reloaded on every agent run.

### Bug Fixes

* `LiteLlm`: arg parsing error and python 3.9 compatibility.
* `DatabaseSessionService`: adds the missing fields; fixes event with empty
  content not being persisted.
* Google API Discovery response parsing issue.
* `load_memory_tool` rendering issue in Dev UI.
* Markdown text overflows in Dev UI.

### Miscellaneous Chores

* Adds unit tests in Github action.
* Improves test coverage.
* Various typo fixes.

## 0.1.0

### Features

* Initial release of the Agent Development Kit (ADK).
* Multi-agent, agent-as-workflow, and custom agent support
* Tool authentication support
* Rich tool support, e.g. built-in tools, google-cloud tools, third-party tools, and MCP tools
* Rich callback support
* Built-in code execution capability
* Asynchronous runtime and execution
* Session, and memory support
* Built-in evaluation support
* Development UI that makes local development easy
* Deploy to Google Cloud Run, Agent Engine
* (Experimental) Live(Bidi) audio/video agent support and Compositional Function Calling(CFC) support
