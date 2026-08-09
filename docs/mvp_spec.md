# CLI版MVP仕様

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

## MVPの対象外

- OCR
- スキャン画像のみのPDF
- SQLite
- PySide6 GUI
- 会話履歴
- FAISSまたはChromaによる永続化
- クラウドLLM
- LangChain
- LlamaIndex
- PDFインデックスの永続化または再利用
- フォルダやglobによるPDFの自動収集

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

## 後続Issueで決定する事項

次の値は現時点では固定せず、それぞれの機能を実装する後続Issueで事前に決定する。

- チャンクサイズ
- チャンクのオーバーラップ
- 検索件数
- 埋め込みモデル名
- 生成モデル名
