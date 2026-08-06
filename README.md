# research-rag

## プロジェクト概要

`research-rag` は、研究資料として使用するPDFをローカル環境で検索し、その内容に基づく回答と根拠を提示するRAGアプリケーションです。

## 現在の開発段階

現在は、テキストを含む単一PDFをCLIで扱うMVPに向けて、開発基盤と仕様を整備している段階です。現時点ではアプリケーション機能は未実装です。

MVPの範囲と完了条件は [`docs/mvp_spec.md`](docs/mvp_spec.md) を参照してください。

## 必要な環境

- Python 3.11以上

## 開発環境のセットアップ

macOSでは、リポジトリのルートで次のコマンドを実行して仮想環境を作成し、有効化します。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

続いて、プロジェクト本体と開発用依存ライブラリを編集可能モードでインストールします。

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## テスト

仮想環境を有効化し、開発用依存ライブラリをインストールした状態で実行します。

```bash
python -m pytest
```

現時点ではアプリケーション機能とテストケースは未実装です。
