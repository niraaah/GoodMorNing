# 현재 서비스 DB 명세

기준: 2026-11-27 (PostgreSQL 전환 반영). 초기 진행계획서 17~23쪽의 상품·판매처·수집 구분을 유지하고, 현재 스티커·폴라로이드·다이어리 기능에 맞춰 정리했다. 초기 문서의 SAM 3D/미니룸, 매장 재고 중심 구조는 현재 구현 명세와 구분한다.

## 저장 위치와 운영 범위

- 현재 DB는 사용자 PC의 Docker 컨테이너 `goodmorning-postgres`(PostgreSQL 17 + pgvector 0.8.7, `127.0.0.1:55432`)이다. API와 로컬 검색 서버가 같은 DB를 사용한다. 자료는 Docker 볼륨 `goodmorning-pgdata`, 비밀번호는 `data/postgres.key`에 있다.
- 에셋 원본·생성 파일은 `data/assets/`, 다이어리 첨부는 `data/notebook-files/`, 수집 상품 썸네일은 `data/catalog-images/`에 보관한다. DB에는 파일 참조와 메타데이터를 저장한다.
- 상품 임베딩은 실제 차원과 모델 revision을 기록한 float32 벡터로 DB에 저장한다. 사진 검색에 올린 사용자 사진과 검색 벡터는 검색 서버 메모리에서만 처리한다. 스티커 제작을 요청한 원본 사진의 기존 저장 동작은 유지한다.
- DB·백업·이미지·키는 Git과 Pages 배포에서 제외한다. 브라우저는 인증된 로컬 API를 통해 접근하며 DB 자체를 공개하지 않는다. `/admin` 조회 화면은 소유자 접근 키로만 열리고, SELECT 권한만 있는 `goodmorning_reader` 계정으로 읽기 전용 조회만 한다.

## 이번에 추가한 테이블

정확한 컬럼·제약은 앱 표는 `server/schema.sql`, 카탈로그는 `server/goods/catalog.sql`이 실행 명세다. 모든 시간은 TIMESTAMPTZ(UTC)이고 JSON은 JSONB이며, 가격은 현재 수집처 기준 KRW 정수다. 모르는 배송비·가격은 NULL, 재고는 unknown이다.

| 테이블 | 역할·주요 항목 |
| --- | --- |
| catalog_products | 공통 상품: 이름·제조사·설명·검증 상태 |
| catalog_variants | 크기·색상·발매 차수 등 버전: product_id·name·attrs·barcode |
| catalog_malls | 판매처: 이름·origin·수집 방식(api/crawl) |
| catalog_offers | 판매처별 후보: external_id·상품명·URL·이미지 URL·가격·관측 시각·선택적 variant_id |
| catalog_offer_history | 판매 정보의 최초 관측 및 가격 변경 기록. 현재 수집기는 배송비·재고를 확정하지 않음 |
| catalog_collect_jobs | 판매처별 수집 결과·시작/종료 시각·개수. 검색어는 해시만 저장 |
| catalog_raw_listings | 수집 당시 공개 상품 필드와 매칭 검토 상태. 인증 헤더나 설정 원문은 저장하지 않음 |
| catalog_query_cache / catalog_query_offers | 검색어 해시별 수집 상태·발견 상품 연결. 수집 요청은 15분 캐시, 상품 행은 계속 보관 |
| catalog_images | 판매처 상품 이미지의 로컬 파일·내용 해시·해상도·관측 시각 |
| catalog_embeddings | 판매 후보별 image/text pgvector 벡터·모델·revision·차원·내용 해시. 사용자 검색 벡터는 제외 |
| asset_product_links | 에셋 소유자·사용자가 선택한 판매 정보·당시 정보 스냅샷·확인 방식·확인 시각 |
| schema_migrations | 적용한 DB 구조 버전 |

## 상품과 내 에셋을 연결하는 규칙

1. 수집한 판매 정보는 먼저 offer/raw_listing 후보로 저장한다. AI 유사도만으로 여러 판매처의 상품이나 버전을 합치지 않는다.
2. 상품·버전의 기준 테이블은 준비하되, 검증용 관리 기능이 생기기 전에는 자동으로 채우지 않는다. offer.variant_id는 미확정 상태에서 NULL을 허용한다.
3. 사용자가 추천을 고르고 스티커 생성이 성공하면 에셋·소유권·asset_product_links를 같은 트랜잭션에 저장한다. 한 사람의 선택이 공용 카탈로그 검증을 의미하지 않는다.
4. 직접 입력한 구매 링크는 개인 에셋 연결 스냅샷에 저장한다. 이를 다른 사용자가 보는 공용 상품 목록으로 자동 공개하지 않는다. 상품 연결을 건너뛰어도 스티커를 만들 수 있다.
5. 기존 에셋의 `metadata.goods`는 호환성을 위해 유지한다. 사용자 확인 기록이 있는 기존 연결만 새 관계 테이블로 보충한다. 기존 에셋·다이어리 본문은 변경하지 않는다.

## 수집과 검색

API 키 없이도 허용된 공식몰의 Scrapy/Playwright 수집 경로로 후보를 저장한다. 쿠팡 API는 키가 있을 때의 선택 경로이며, 수집 제한을 우회하지 않는다. 현재 등록 수집처는 포켓몬스토어·대원샵 및 선택적인 쿠팡이다.

검색어와 과거 검색 연결에 해당하는 상품을 최대 32개 가져와 이미지 또는 설명 임베딩으로 순위를 매긴다. 이는 전체 카탈로그를 검색하는 ANN 벡터 인덱스가 아니다. 같은 검색어의 과거 상품은 판매처 접속이 실패해도 남고, 처음 보는 검색어는 기존 상품명이 맞는 경우만 후보가 생긴다. 목록이 비어 있으면 자동으로 외부 전체 상품이 채워지는 것은 아니다.

상품 이미지의 로컬 저장본은 24시간 재사용하며 이후 갱신을 시도한다. 갱신 실패 시 이전 저장본을 사용할 수 있다. 내용 해시와 모델 revision이 같은 임베딩은 재사용한다. 이미지가 없으면 텍스트 비교임을 표시한다. 24시간이 지난 판매 정보는 이전 수집 정보로 표시하고 수집 날짜를 보여 준다. 수집 시각은 실시간 가격·재고 보장이 아니며, 최종 옵션·가격은 구매처에서 확인한다.

## 회원·다이어리 구조 (2026-11-27)

`server/diary_schema.sql`에 다음 테이블을 추가했다. 기존 `notebook_pages.body` JSON은 현재 API의 기준 데이터로 유지하며, 저장할 때 아래 페이지·배치 테이블도 같은 트랜잭션에서 갱신한다. 페이지별 advisory lock으로 동시에 저장한 JSON과 배치가 서로 달라지는 것을 방지한다.

| 테이블 | 역할 |
| --- | --- |
| app_users | UUID 사용자. local·guest·member·legacy 구분. 현재는 소유자와 방문자만 생성 |
| app_owner_bindings | 기존 private/guest 소유권 문자열과 사용자 UUID 연결. 자동 계정 합치기는 하지 않음 |
| auth_identities | 이후 로그인 제공자의 provider·subject와 사용자 연결을 위한 구조. 현재는 비어 있으며 로그인·세션 기능은 미구현 |
| user_notebooks | 사용자별 기본 다이어리. 사용자·notebook_key 조합으로 구분 |
| diary_pages | 기본 다이어리의 페이지, 기존 owner/page_key 참조, 속지 설정, 원본 해시·수정 시각 |
| diary_page_items | 페이지 개체의 독립 UUID·종류·배열 슬롯·레이어 순서·위치·크기·회전·메모·삭제 상태·파일/에셋 참조·원본 속성 |

사진의 layer_group은 0, 스티커는 1로 DB에서 생성한다. 사진 안의 앞뒤 순서는 layerOrder를 순위로 정리하며, 스티커는 그 위에 둔다. 같은 에셋을 여러 번 배치해도 행은 서로 다르다. 현재 프론트가 사용하는 배열 슬롯을 배치 식별의 기준으로 유지하므로, 향후 배열 재배열 API를 만들 때는 클라이언트가 독립 배치 ID를 전달하도록 전환해야 한다. 사진 배열의 숨김·빈 자리도 원본 그대로 보존하며, 화면에 그릴지 여부는 현재 렌더러 규칙을 따른다.

기존 JSON의 미인식 필드·사진 메모·속지·첨부 참조는 삭제하지 않는다. 에셋과 파일의 관계는 실제 존재하는 참조만 FK로 연결하며, 샘플/옛 경로 등은 원본 속성에 남긴다. 기존 `diaries`는 이전 Flutter 편집기의 호환 데이터로 유지하며, 현재 사용하는 `notebook_pages`를 새 구조에 반영한다. 사용자 데이터의 접근 제어는 기존 owner 기준 API가 계속 담당한다. 테이블 추가는 회원 가입이나 로그인 완료를 의미하지 않는다.

`scripts/migrate_diary_structure.py`는 두 서버가 중지된 것을 확인하고 로컬 PostgreSQL 전체를 `data/backups/*.dump`로 백업한다. 백업 목차를 확인한 뒤 새 테이블 생성·이관·재실행·페이지별 원본과 배치 속성 비교·기존 테이블 지문 비교를 한 트랜잭션에서 수행한다. 기본 실행은 되돌리며, `--apply`만 커밋한다. 변경되는 이행 이력 테이블은 기존 데이터 지문 비교에서 제외한다. 백업은 생성·읽기 확인을 거쳤으며 전체 복원 연습과는 구분한다.

## 현재 데이터와 이후 목표

| 영역 | 현재 유지 | 이후 목표 |
| --- | --- | --- |
| 사용자 | app_users·app_owner_bindings, 기존 owner 접근 제어 | 로그인 구현·sessions, 동의에 따른 방문자 데이터 계정 이전 |
| 에셋 | assets·asset_trash·파일 디렉터리 | 소유자·파일 종류별 참조 및 삭제/복구 정책 유지 |
| 다이어리 | 기존 JSON과 user_notebooks·diary_pages 동시 저장 | 정규화된 테이블을 기준으로 읽는 API로 단계적 전환 |
| 배치 | diary_page_items의 독립 ID·참조·레이어·변환·원본 속성 | 클라이언트 배치 ID 도입, 배열 슬롯 의존 제거 |
| 폴라로이드 | diaryLayout의 사진·caption·테이프 | photo 개체의 메모·사진 참조. sticker 라이브러리와 분리 |
| 공개/훔쳐보기 | 현재 원본 샘플 화면 | 명시적 공개 범위·공개 시점·접근 제어. 개인 DB가 자동 공개되지 않음 |
| 근처 사용자 | 미구현 | 동의·최근 위치·정확도·만료 시각·차단·알림 중복 방지 |

페이지의 배치 삭제와 에셋함 삭제는 구분한다. 같은 스티커를 여러 번 붙일 때 각 배치는 독립 ID를 가져야 하며, 현재 프로토타입의 에셋 ID 중복 제한은 이후 배치 모델 분리 시 해소한다. 폴라로이드는 항상 스티커 아래 레이어에 두고, 자이로 센서 값은 매 프레임 DB에 저장하지 않는다.

## PostgreSQL 전환

초기 계획의 목표는 PostgreSQL + pgvector + PostGIS이며, 모두 같은 사용자 PC에 둔다. 2026-11-27에 SQLite에서 PostgreSQL로 옮겼다.

- 표 이름·문자열 ID·열 순서는 SQLite와 같다. JSON 문자열은 JSONB, UTC 초와 ISO 시각은 TIMESTAMPTZ, 0/1 표시는 boolean으로 바꿨다. 정수 자동 번호는 identity로 바꿨다.
- `catalog_embeddings`의 float32-le 바이트는 pgvector `vector`에 넣고, 차원은 `vector_dims(vector) = dimensions` 제약으로 확인한다. 차원 고정 열과 ANN 인덱스는 두지 않는다. 모델 revision·차원이 다른 벡터는 지금처럼 키로 구분한다.
- SQLite의 `BEGIN IMMEDIATE`로 막던 동시 저장은 다이어리별 advisory lock과 에셋 행 잠금으로 바꿨다.
- 남은 일: catalog/online/ingest 스키마 분리, 로그인·세션 구현과 방문자 소유권 이전 후 나머지 에셋·상품 테이블의 회원별 FK, 근처 사용자 기능의 PostGIS.

## 이행과 확인 범위

`python scripts/migrate_postgres.py`는 `data/goodmorning.sqlite3`을 `data/backups/`에 백업한 뒤, 그 사본을 PostgreSQL에 한 트랜잭션으로 옮겨 보고 되돌린다(연습). 두 서버를 멈춘 뒤 `--apply`로 실제 이행한다. 진행 중인 작업이 있거나, 대상 PostgreSQL에 이미 자료가 있거나, 표별 행 수·임베딩 차원이 맞지 않으면 중단한다. 원본 SQLite 파일과 `data/` 아래 파일은 바꾸지 않는다. 이전의 SQLite 전용 `scripts/migrate_catalog.py`는 카탈로그 표가 PostgreSQL 스키마에 포함되면서 삭제했다.

상품 수집·사진 검색·휴대폰 조작의 기능 검증은 사용자 진행 범위다. DB 구조 적용과 무결성 확인이 실제 판매처 수집 성공이나 검색 품질을 보장하지 않는다.
