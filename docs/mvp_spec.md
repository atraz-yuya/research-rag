# Research RAG MVP仕様

## MVPの対象

- テキストを含む1つ以上のPDF
- CLI上での操作
- PDFからページ単位で文章を取得する
- 利用者に表示するページ番号はPDFごとに1始まりとする
- 1つのチャンクが複数ページをまたがないようにする
- 複数PDFのチャンクを1つの共有検索空間へまとめる
- 質問に関連するチャンクを全PDF横断の順位で検索する
- 検索結果をローカルLLMへ渡して回答を生成する
- 回答とともにPDF名、ページ番号、根拠文章を表示する
- 追加PDFはCLIの`--pdf`を繰り返して指定する
- PDF、チャンク、embeddingは実行中のメモリ内だけで扱う
- 同じPDF集合へ複数回質問するときは、immutableなインメモリindexを再利用できる
- 準備済みindex全体をSQLiteへ保存・一覧・読込・削除できる
- 永続corpusの各文書についてsource fileの状態を確認できる
- 永続corpusへ文書単位で追加・削除・再indexできる
- 永続corpusへ任意の表示名を付け、名前変更とcorpus全体の削除ができる
- PySide6デスクトップGUIで保存済み資料セットを管理し、質問できる
- GUIで資料セット内の文書名、source path、`CURRENT`／`MODIFIED`／`MISSING`／`UNKNOWN`状態を確認できる
- PySide6公式の`pyside6-deploy`でローカル動作確認用のstandalone macOS `.app`を再現できる
- stable bundle identifierとproject versionを反映したmacOS `.app`を再現できる
- credentialを外部から渡すrelease helperでDeveloper ID署名、hardened runtime、notarization、stapling、配布ZIP作成を実行できる

## MVPの対象外

- OCR
- スキャン画像のみのPDF
- 会話履歴
- FAISSまたはChromaによる永続化
- クラウドLLM
- LangChain
- LlamaIndex
- フォルダやglobによるPDFの自動収集
- source fileの自動監視・自動再index
- 欠落PDFの移動先検索やrename workflow
- DMG／Mac App Store配布
- custom app icon
- auto update
- cross-platform installer
- GitHub Release automation

## エラーとして扱うもの

- 指定したPDFが存在しない
- 指定したPDFを開けない
- 選択したすべてのPDFから検索可能な文章を抽出できない
- 同じbasenameのPDFが複数指定されている
- 質問が空文字である
- Ollamaが起動していない
- 指定したモデルが利用できない

## MVPの完了条件

1つ以上のPDFを指定して質問を入力すると、全PDFを横断した検索結果に基づく回答と、根拠となるPDF名、ページ番号、文章が表示されること。従来の単一PDF指定でも同じ形式で利用できること。

一部のPDFから文章を抽出できなくても、ほかのPDFに検索可能な文章があれば処理を続ける。各PDFは1回だけ抽出し、結合したチャンク群のembedding、質問embedding、検索、回答生成はそれぞれ1回だけ実行する。

## インメモリindexのライフサイクル

`build_rag_index()`はPDF extraction、production Chunkerによる分割、文書Chunkのembeddingを担当し、PDF名、build時のembedding model、`EmbeddedChunk`を保持するimmutableな`RagIndex`を返す。indexはOllama clientやgeneration modelを保持しない。

`answer_question_from_index()`は、indexに記録されたembedding modelで質問を1回だけembeddingし、保存済みの全`EmbeddedChunk`を横断検索して回答を生成する。文書側処理は行わないため、同じindexへの2回目以降の質問でもPDF extraction、chunking、文書embeddingは再実行されない。

既存の`answer_question_from_pdf()`と`answer_question_from_pdfs()`は、内部でbuildとanswerを合成する互換APIとして維持する。CLIの構文と出力形式は変更しない。

## SQLite永続化仕様

`SQLiteRagIndexStore`が永続化だけを担当し、`RagIndex`はSQLite connectionや永続IDを保持しない。Python標準の`sqlite3`、`uuid`、`struct`だけを使い、schema version 3を`store_metadata`へ明示する。schema v1／v2は1つのtransaction内でv1→v2→v3の順に明示的に移行し、全migration成功後にだけversionを3へ更新する。既存データと永続IDを維持し、未対応versionはmigrationを推測せずエラーにする。

indexと各documentにはUUIDを割り当て、documentの入力順、名前、正規化した絶対source pathを保存する。Chunkは全PDF横断の順序、PDF名、1始まりページ番号、page内chunk index、本文を保持する。source PDFが削除または一時的に利用不能でも、保存済みChunkとembeddingから`RagIndex`を復元できる。

embeddingはpickleを使わずlittle-endian IEEE-754 float64 BLOBとして保存し、dimensionも別列へ保存する。load時にdimension、BLOB長、非有限値を検査し、破損したindexを部分的に返さない。

各documentにはnullableな`content_sha256`、`file_size`、`mtime_ns`、`indexed_at`も保存する。schema v1から移行した文書ではこれらをNULLに保ち、保存済みembeddingが現在のsource file由来だと推測しない。schema v2では`index_id`と`document_id`の複合外部キーにより、別indexのdocumentへChunkを関連付けられないようにする。

schema v3では`rag_indexes.display_name`をnullableな表示metadataとして保存する。`index_id`がdurable identityであり、名前変更でindex／document IDやembeddingを変更しない。表示名は前後空白を除去し、空文字と100文字超を拒否する一方、異なるcorpus間の重複は許可する。v1／v2から移行したcorpusでは名前をNULLに保ち、GUIは従来の先頭PDF名と文書数によるラベルへfallbackする。

1つのindex保存と各document mutationはそれぞれ単一transactionで行い、途中失敗時は全行をrollbackする。index削除時はforeign key cascadeでdocumentとchunkも削除する。`list_indexes()`と`get_index_metadata()`はembedding BLOBを読み込まず、軽量metadataだけを返す。既存CLIは自動的にdatabaseを開かず、永続化用の新しいCLI構文も追加しない。

## 永続文書ライフサイクル仕様

`PersistentRagDocumentManager`がfilesystem、PDF processing、Ollamaと永続化層を接続する。`SQLiteRagIndexStore`のSQL methodはPDFを読まず、Ollamaも呼ばない。

`create_index()`は全source fileをSHA-256でfingerprintし、productionの`build_rag_index()`を実行後に再度fingerprintする。前後のSHA-256が一致した場合だけ、indexとfingerprintをatomicに保存する。既存の低水準`save_index()`は互換維持し、任意のprebuilt indexへ信頼できるfingerprintを推測して付与しない。

`inspect_documents()`は文書順を保ち、既存の各source fileを1回だけstreaming hashする。保存SHAと一致すれば`CURRENT`、異なれば`MODIFIED`、保存pathが通常ファイルでなければ`MISSING`、信頼できる保存SHAがなければ`UNKNOWN`とする。変更判定はSHA-256を正とし、sizeとmtimeだけでは`MODIFIED`にしない。inspectionではPDF抽出、chunking、embedding、検索、生成、DB mutationを実行しない。

`add_document()`はduplicate basenameを外部処理前に拒否し、新規PDFだけを保存済みembedding modelで処理して末尾へ追加する。`remove_document()`はsource fileを削除せず、選択文書とそのChunkだけを削除し、残る文書位置とglobal Chunk位置を連続化する。最後の検索可能文書を削除する操作は拒否する。`reindex_document()`は保存source pathの対象文書だけを再処理し、同じdocument IDとpositionを維持してChunkとfingerprintをatomicに置換する。

すべてのmutationでindex IDを維持し、変更しない文書のID・Chunk・embeddingを再生成しない。global Chunk順はdocument position昇順、その文書内のproduction Chunk順とする。add／reindexも処理前後のSHA-256を比較し、source fileの途中変更やPDF／Ollama／DB failure時には以前のcorpusを使用可能なまま保つ。

## デスクトップGUI仕様

GUIは`python -m research_rag.gui_app`で起動する。既存CLIの構文・既定値・動作は維持し、GUIとCLIは同じproduction RAG機能を使用する。GUIの既定値はembedding model=`qwen3-embedding:0.6b`、generation model=`qwen3:4b-instruct`、top_k=`3`とし、CLIと共通の定数から参照する。

GUIの既定DBは`QStandardPaths.AppDataLocation`配下の`indexes.sqlite3`とする。テストではDB pathを注入し、実ユーザーデータ領域へ書き込まない。元PDFはアプリケーションデータ領域へコピーせず、資料の削除でも元PDFを削除しない。

GUI runtime設定はimmutableなsnapshotとして扱い、Embedding model、Generation model、Top-K、Ollama base URLを設定画面で編集できる。値はmodel名の空文字、Top-Kの1未満または100超、HTTP(S) host URLでない接続先を適用前に拒否し、Ollama URL末尾の`/`は正規化する。既定値はembedding=`qwen3-embedding:0.6b`、generation=`qwen3:4b-instruct`、Top-K=`3`、URL=`http://localhost:11434`とする。

設定はcorpus SQLiteとは別の`QSettings` INIとして、既定DBと同じapplication data directoryの`settings.ini`へatomicに保存する。初回起動と保存値が不正な場合は安全な既定snapshotを使用する。適用時にOllamaへnetwork callは行わず、保存失敗時は同じclientを含む直前のlive snapshotへrollbackしてlive設定と永続設定の不一致を残さない。SQLite schemaはversion 3のまま変更しない。

Embedding model設定は新規corpus作成時だけ使用する。既存corpusの`embedding_model`を変更せず、質問のquery embedding、文書追加、再インデックスはindexに保存済みのmodelを使い続ける。選択中corpusが実際に使用するmodelをGUIに表示する。Generation modelとTop-Kは設定保存後の質問から使用し、Ollama URL変更時はGUI serviceとdocument managerを同一の新しいclientへ切り替える。worker処理中は設定操作を無効化する。

起動時は`SQLiteRagIndexStore.list_indexes()`の軽量metadataから保存済み資料セットを表示し、永続表示名を優先する。名前がない既存corpusはPDF名ベースのラベルを使い、UUIDは内部item dataとして保持して表示文字列から解析しない。資料セット選択時は`PersistentRagDocumentManager.inspect_documents()`を使い、文書順を保って文書名、状態、source pathを表示する。

新規資料セットは1つ以上のPDFと表示名からatomicに作成でき、選択中の資料セットはRAG内容やUUIDを変えずに名前変更できる。選択中の資料セットにはPDFを1件ずつ追加でき、選択文書は保存済みsource pathから再インデックスできる。文書削除と資料セット全体の削除では、確認ダイアログで元PDFが削除されないことを明示する。資料セット全体の削除は既存workerを使ってSQLite内の関連行をcascade削除し、最後の資料セットを削除した後は文書・回答・参照表示を空にする。状態更新はfilesystem fingerprintだけを確認し、PDF extractionやOllamaを実行しない。

質問時は保存済みindexをloadし、`answer_question_from_index()`を使用する。回答本文と、各参照元のrank、PDF名、PDFごとに1始まりのページ番号、cosine similarity score、source textを表示する。会話履歴は保持しない。

worker処理中は`minimum=0`／`maximum=0`のindeterminate progress indicatorと操作別の日本語メッセージを表示する。pipelineは信頼できる進捗率を公開していないため、擬似的なpercentageは表示しない。成功時は操作別の完了メッセージへ遷移し、失敗時はindicatorとbusy状態を必ず解除して`処理に失敗しました`と表示する。失敗によって質問入力、既存回答・参照、選択corpus、正常に描画済みの文書tableを不要に消去しない。

corpusがない場合は実itemを追加せず独立したlabelで新規作成を案内し、corpus未選択時もdocument areaに案内を表示する。回答・参照の説明は`placeholderText`とし、実回答データと区別する。最後のcorpus削除後はこれらのempty stateへ戻す。

`DocumentStatus`の`CURRENT`／`MODIFIED`／`MISSING`／`UNKNOWN`は内部値とinspection logicを維持し、GUIだけでそれぞれ`最新`／`変更あり`／`ファイルなし`／`未確認`と表示する。各statusの意味はtooltipで説明し、document UUIDは引き続き資料名itemのQt user dataへ保持する。文書tableは資料名を調整可能な読みやすい幅、状態をcontent幅、保存元pathを残り幅とし、path全体はtooltipでも確認できる。

WidgetはSQL、PDF処理、Chunking、embedding、retrieval、generationを実装せず、GUI service/controller層を介して既存のstore、document manager、RAG serviceを呼び出す。資料セット作成、文書追加、再インデックス、状態確認、質問は`QThreadPool`／`QRunnable`でGUI thread外に実行する。処理中は競合操作を無効化し、成功・失敗のどちらでもUIを復帰させる。失敗時はエラーダイアログを表示し、入力内容と保存済み資料セットを失わない。

## macOS application packaging仕様

repository直下の`run_gui.py`は`research_rag.gui_app.main()`だけを呼び出すdeploy用launcherとし、GUI初期化やRAG処理を複製しない。`pysidedeploy.spec`はPySide6公式`pyside6-deploy`のstandalone modeを使用し、成果物をGit管理外の`build/deploy/Research RAG.app`へ生成する。PyInstallerは併用しない。

`scripts/build_macos_app.sh`はmacOSと`pyside6-deploy`の存在を事前検証し、repository内のspecを一時コピーしてbuildする。生成bundleはFinder/resource-fork extended attributeを除去してローカル用ad-hoc署名を付け、実行ファイルの存在とstrict code-signature validationを成功条件とする。このlocal helperはApple Developer credentialsを要求せず、Developer ID署名は行わない。通常のpytestは設定とhelperのintegration boundaryだけを検証し、Nuitkaによるfull buildは実行しない。

macOS bundle identifierは`io.github.atraz-yuya.research-rag`で固定する。versionの唯一のsourceは`pyproject.toml`の`[project].version`とし、packaging時に`CFBundleShortVersionString`と`CFBundleVersion`へ同じ値を反映する。production Python packageへversion定数を複製しない。

`scripts/release_macos_app.sh`はlocal helperと分離し、環境変数で明示されたDeveloper ID Application identityとnotarytool Keychain profileを必須とする。ad-hoc署名へfallbackせず、hardened runtimeとsecure timestampを伴う署名、signature／entitlement検証、`ditto`による事前ZIP、`xcrun notarytool submit --wait`、staple／validate、codesign／Gatekeeper検証を順に行う。Accepted後にだけ、実際のMach-O architectureとproject versionを名前に含む最終ZIPを`build/release`へ生成する。notarization失敗時はsubmission IDとlog確認経路を残す。`--dry-run`は必要値とstageだけを表示し、署名、Keychain変更、network accessを行わない。

release identityのcertificate／秘密鍵／password／Team ID、notary credentialはGit管理しない。release scriptはKeychain profile名だけを受け取り、`altool`やplaintext passwordを使用しない。DMG、Mac App Store、GitHub Release automation、custom iconは対象外とする。

bundleへcorpus DBの`indexes.sqlite3`、GUI設定の`settings.ini`、source PDF、Ollama本体、Ollama modelを含めない。runtime data pathは既存の`QStandardPaths.AppDataLocation`を維持し、bundle内部へDBや設定を書き込まない。Ollama接続には保存済みGUI runtime設定のbase URLを使用する。corpus SQLite schemaはversion 3のままとし、CLI、`python -m research_rag.gui_app`、worker／teardownの動作を変更しない。

## 後続Issueで決定する事項

次の値は現時点では固定せず、それぞれの機能を実装する後続Issueで事前に決定する。

- チャンクサイズ
- チャンクのオーバーラップ
- 検索件数
- 埋め込みモデル名
- 生成モデル名
