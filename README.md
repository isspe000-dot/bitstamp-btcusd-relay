# Bitstamp BTC/USD 06:59 KST 확정봉 중계

매일 KST 기준 전일·당일의 BTC/USD 1분봉 종가를 공식 Bitstamp OHLC API에서 각각 조회합니다. 대상 봉은 06:59:00에 시작하고 07:00:00에 마감합니다. 두 날짜 모두 KST에서 계산한 Unix 초와 정확히 일치하는 봉이 한 개이고 종가가 양수인 경우에만 채점값을 기록합니다. 쿼리에 `step=60`과 `exclude_current_candle=true`를 사용합니다.

## GitHub에 올리기

1. ZIP을 풀고 파일을 GitHub 공개 저장소의 기본 브랜치 루트에 커밋합니다. 숨김 폴더 `.github/workflows/`도 포함합니다. 새 전용 저장소를 사용하면 중계 파일만 공개됩니다.
2. 저장소에서 GitHub Actions를 활성화하고 워크플로가 기본 브랜치에 커밋할 수 있도록 설정합니다. 워크플로는 기본 제공 `GITHUB_TOKEN`과 `contents: write`를 사용합니다. 저장소 또는 조직의 브랜치 보호 규칙이 해당 푸시를 막으면 게시 단계에서 실패합니다. 거래소 API 키와 별도 GitHub 비밀값은 필요 없습니다.
3. KST 07:00 이후 **Actions → Collect finalized Bitstamp candles → Run workflow**에서 기본 브랜치로 첫 실행을 확인합니다. 날짜 입력을 비우면 실행 시작 시점의 KST 날짜를 사용합니다. 과거 날짜를 입력하면 해당 날짜의 보고서만 갱신합니다.
4. 기본 브랜치에 `public/latest.json`이 커밋되면 아래 Raw URL에서 읽을 수 있습니다. `OWNER`, `REPO`, `BRANCH`를 실제 값으로 바꿉니다.

| 파일 | 공개 읽기 주소 |
| --- | --- |
| 최신 보고서 | `https://raw.githubusercontent.com/OWNER/REPO/BRANCH/public/latest.json` |
| 날짜별 보고서 | `https://raw.githubusercontent.com/OWNER/REPO/BRANCH/public/reports/YYYY-MM-DD.json` |

GitHub Pages 주소가 필요하면 별도 Pages 워크플로에서 `public/`을 정적 파일로 배포하는 구성을 추가할 수 있습니다. 이 저장소는 Raw 게시 경로를 제공합니다. [GitHub Pages 워크플로 문서](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)

## 예약과 지연

- UTC cron `3 22 * * *`은 다음 날 **07:03 KST**입니다. GitHub Actions는 정각에 실행이 몰리며, 예약 실행이 지연되거나 누락될 수 있습니다. 07:05 KST까지 조회와 게시가 완료된다는 보장은 없습니다. 공개 저장소에 활동이 60일간 없으면 예약 워크플로가 비활성화될 수 있습니다. [GitHub 예약 실행 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- 당일 봉이 마감되기 전에는 조회하거나 게시하지 않습니다. 예약이 누락되면 수동 실행에서 복원할 KST 날짜를 입력합니다. 같은 보고서 날짜를 다시 실행하면 파일을 갱신하며 이전 결과는 Git 커밋 기록에 남습니다.
- `backfilled`는 검증에 성공한 Bitstamp 요청이 해당 봉 날짜의 **07:05 KST 이상**이면 `true`입니다. 전일 재조회와 지연된 당일 재조회가 이에 해당합니다. 시각 기준은 API 요청 시작 시점입니다. 파일의 07:05 이전 게시 여부를 판정하려면 별도로 소비 시점에 공개 경로를 확인해야 합니다.

## JSON 읽기 규칙

형식은 [report.schema.json](report.schema.json)의 JSON Schema Draft 2020-12를 따릅니다.

| 항목 | 의미 |
| --- | --- |
| `as_of_date_kst`, `started_at_utc` | 보고서의 KST 기준일과 실제 실행 시작 시각 |
| `previous`, `current` | 기준일 전일과 당일의 기록. 봉의 시작·마감 시각과 기대 Unix 초를 포함 |
| `bitstamp` | 실제 요청 URL, 최종 시도 요청 시작 시각(UTC), 검증된 Unix 초와 USD 종가 또는 실패 사유 |
| `backfilled` | Bitstamp 검증에 성공했을 때 사후 복원 여부. 검증 실패 시 `null` |
| `kraken_comparison` | Bitstamp 실패 시에만 채우는 비교 조회 결과. Kraken의 진행 중인 마지막 봉은 제외 |

채점 시 `as_of_date_kst`가 의도한 브리핑 날짜인지 먼저 확인하고, 각 날짜의 `bitstamp.status == "verified"`와 `bitstamp.timestamp_unix == expected_timestamp_unix`를 확인한 후 `bitstamp.close_usd`를 사용합니다. 종가는 정밀도 보존을 위해 문자열로 저장합니다. 확인에 실패한 날짜는 결측으로 처리합니다. Kraken 비교값은 같은 분이 검증된 경우에만 비교 필드에 기록하며, Kraken은 최근 720개 봉까지만 제공하므로 전일 1분봉 비교는 일반적으로 결측입니다. [Bitstamp OHLC API](https://www.bitstamp.net/api/#tag/Market-info/operation/GetOHLCData) · [Kraken OHLC API](https://docs.kraken.com/api-reference/market-data/get-ohlc-data)

Bitstamp는 날짜당 최대 두 번 요청합니다. 두 날짜가 모두 검증되면 수집기는 종료 코드 `0`을 반환합니다. Bitstamp 결측이 있으면 보고서를 기록한 뒤 `3`을 반환합니다. Actions는 이 경우에도 보고서를 게시하고 실행 결과에 실패를 표시합니다.

## 로컬 실행

Python 3.12 이상과 공개 API에 대한 HTTPS 접근이 필요합니다. 외부 Python 패키지는 필요 없습니다. 테스트는 거래소 응답을 모의 처리합니다.

```sh
python -m unittest discover -s tests -v
python collect.py
python collect.py --as-of-date 2026-11-07 --output-dir ./check
```
