# GoodMorNing 구현·수정 작업 이력

발표·보고용 기록입니다. Git 이력과 로컬 적용 결과를 근거로 작성하며, 공동 기여자의 변경도 프로젝트 이력으로 포함합니다. 날짜는 저장소 커밋 기준입니다. 구현/빌드 완료와 사용자의 실제 기능 확인을 구분합니다. API 키·접속 토큰·개인 사진·DB 원본은 기록하지 않습니다. 마지막 갱신: 2026-11-27.

## 서비스와 구성

사진에서 굿즈를 선택해 SAM 2로 배경을 제거하고, YOLO 깊이 정보와 단일 사진 기반 Gaussian relief로 볼록 스티커를 만듭니다. 생성한 에셋과 폴라로이드를 다이어리에 붙이고, 휴대폰 움직임에 맞춰 반짝임을 표현합니다. 상품 검색 결과는 사용자가 선택해 구매 페이지와 연결합니다.

Flutter Web 안에서 원본 HTML/CSS/JS 프로토타입을 함께 사용하는 구조입니다. GitHub Actions가 프론트를 빌드해 GitHub Pages에 배포하고, API·DB·모델 처리는 로컬 Windows PC에서 실행합니다. SAM 2/YOLO는 DirectML, 현재 EmbeddingGemma 2는 CPU로 실행합니다. GitHub Actions가 GPU 작업을 수행하는 구성은 아닙니다.

## 구현·수정 이력

| 날짜 | 해결한 문제 / 구현 내용 | 근거 |
| --- | --- | --- |
| 11-26 | Flutter 웹 앱과 로컬 SAM 2·Gaussian 스티커 생성 서버 기반 구성. 사진 입력·에셋·다이어리 연결 | [fc64422](https://github.com/niraaah/GoodMorNing/commit/fc64422) |
| 11-26 | GitHub Pages 배포, 원본 프로토타입 홈 연결, 로컬 GPU 서버 외부 연결 구성 | [100550d](https://github.com/niraaah/GoodMorNing/commit/100550d) |
| 11-26 | 방문자가 서버 주소·키를 직접 넣지 않아도 연결되게 하고 방문자별 수집방 분리 | [ffc3e16](https://github.com/niraaah/GoodMorNing/commit/ffc3e16) |
| 11-26 | 누락됐던 훔쳐보기 페이지·샘플 다이어리 이동 복원 | [5e6e8b5](https://github.com/niraaah/GoodMorNing/commit/5e6e8b5) |
| 11-26 | 사진 영역 선택과 스크롤 터치 충돌, 저장/취소 후 모달이 닫히지 않던 흐름 수정 | [9e08715](https://github.com/niraaah/GoodMorNing/commit/9e08715) |
| 11-26 | 원본 다이어리 외형·편집 흐름 복원. 자이로 값으로 스티커 광택을 움직이고 센서 미사용 시 수동 보조. 스티커 이름 재입력 확인 후 휴지통 이동·복구 | [96ac6c0](https://github.com/niraaah/GoodMorNing/commit/96ac6c0) |
| 11-26 | 폴라로이드가 스티커 목록에 들어가던 문제 수정. 사진을 스티커 아래에 배치하고 폴라로이드 흰 여백에 손글씨 캡션 적용 | [8e97ad7](https://github.com/niraaah/GoodMorNing/commit/8e97ad7) |
| 11-26 | 로컬 EmbeddingGemma 상품 추천·사용자 확인 상품 연결·구매 링크 구현. 적합한 후보가 없을 때 밝고 선명한 재촬영을 안내 | [7b574e0](https://github.com/niraaah/GoodMorNing/commit/7b574e0) |
| 11-26 | 커밋 전 로컬 비밀값 검사, Gitleaks, CI 보안 검사, Pages 산출물 검사 추가. Windows 훅 줄바꿈 보완 | [d9d8822](https://github.com/niraaah/GoodMorNing/commit/d9d8822), [11bbf4c](https://github.com/niraaah/GoodMorNing/commit/11bbf4c) |
| 11-26 | 다이어리 스티커 접근·이동 문제 및 사진 편집 취소 흐름 보완 | [7da0db0](https://github.com/niraaah/GoodMorNing/commit/7da0db0) |
| 11-26 | 하단 슬라이더 중심 편집을 개체 모서리 크기 조절·상단 작은 툴바로 변경. 교체·삭제 조작 추가 | [7a850af](https://github.com/niraaah/GoodMorNing/commit/7a850af) |
| 11-26 | 상품 후보·임베딩·선택한 상품과 에셋의 연결 정보를 로컬 DB에 저장하도록 구현 | [7741a44](https://github.com/niraaah/GoodMorNing/commit/7741a44) |
| 11-27 | 다이어리에서 동작 센서 사용 안내: 켜기·나중에·다시 켜기 | [26042ef](https://github.com/niraaah/GoodMorNing/commit/26042ef) |
| 11-27 | 회전 버튼을 누르면 적용/취소 모드로 전환하고 모서리 드래그로 회전하는 방식으로 수정 | [09777b6](https://github.com/niraaah/GoodMorNing/commit/09777b6) |
| 11-27 | 공동 기여자의 PostgreSQL·pgvector 전환 및 SQLite 데이터 이관 코드 반영 | [PR #1](https://github.com/niraaah/GoodMorNing/pull/1) |
| 11-27 | 공동 기여자의 SAM 2 누끼 후 YOLO26n 깊이 기반 볼록 형상, 처리 단계 이미지, 관리자 DB 조회 기능 반영 | [PR #2](https://github.com/niraaah/GoodMorNing/pull/2) |
| 11-27 | 폴라로이드 앞으로/뒤로 순서 조절. 모든 폴라로이드보다 스티커가 위에 놓이도록 유지 | [d933c15](https://github.com/niraaah/GoodMorNing/commit/d933c15) |
| 11-27 | 사용자별 Docker 설치 경로 대응, 로컬 PostgreSQL·YOLO 모델 적용, PR 검증 자동화 | [PR #3](https://github.com/niraaah/GoodMorNing/pull/3) |
| 11-27 | 고정 개발 브랜치 `niraaah` → PR → 검사 → `main` 병합 → 배포 방식으로 정리. 개발 브랜치는 유지 | [PR #4](https://github.com/niraaah/GoodMorNing/pull/4) |
| 11-27 | 다이어리 장별 속지 색 6종·무늬 4종, 저장·취소·페이지별 유지 | [PR #5](https://github.com/niraaah/GoodMorNing/pull/5) |
| 11-27 | 사용자 UUID·소유자 바인딩·노트·페이지·배치 테이블 정리. 원본 JSON과 정규화 자료를 같은 트랜잭션에 저장 | [PR #6](https://github.com/niraaah/GoodMorNing/pull/6) |
| 11-27 | 자체 아이디·비밀번호 없이 구글·카카오 로그인 구현. 단회 OAuth 요청·해시 세션·로그아웃·명시적 방문자 자료 연결 | [PR #7](https://github.com/niraaah/GoodMorNing/pull/7) |
| 11-27 | DB 최소 권한·회원별 RLS·내부 검색 인증 분리·로컬 관리자 제한·백업 복원 검증 적용 | [PR #8](https://github.com/niraaah/GoodMorNing/pull/8), 아래 보안 작업 상세 및 [설계 문서](SECURITY.md) |

## 이번 보안 강화 작업

**발견한 문제:** API·검색 서버가 같은 DB 슈퍼유저를 사용했고, 조회 계정도 관리자와 같은 비밀번호를 사용했습니다. 회원 자료 접근은 코드의 소유자 검사에 의존했으며 DB RLS가 없었습니다. 검색 서버의 인증 키도 PC 소유자 키와 같았습니다.

**변경 내용:**

1. API·검색·조회 계정을 별도 비밀번호와 권한으로 분리했습니다. 실행 계정의 슈퍼유저·역할/DB 생성·RLS 우회 권한을 제거하고 서버 시작 시 고권한 연결을 거부합니다.
2. 회원 콘텐츠 12개 테이블에 FORCE RLS를 적용했습니다. 소유자 조건이 빠진 SELECT/UPDATE/DELETE도 다른 회원 자료를 읽거나 바꾸지 못하게 하고, 백그라운드 작업에도 소유권을 전달합니다.
3. 검색 계정은 상품 수집·이미지·임베딩 테이블만 처리합니다. 회원·인증·다이어리·개인 에셋 테이블 접근을 DB에서 거부합니다.
4. 검색 전용 키를 새로 분리하고 크롤러에 비밀 환경변수가 상속되지 않도록 했습니다. DB 관리 화면은 로컬 PC에서만 접근할 수 있게 했습니다.
5. 스키마 생성과 권한 부여를 실행 서버에서 분리했습니다. 기존 SQLite 이관 시 새 보안 버전 이력을 보존하고, 이관 후 암묵적 소유권도 RLS용으로 보충하도록 호환성을 수정했습니다. 기존 키 누출 검사도 새 DB·서비스 키 파일 전체를 검사하도록 확장했습니다.
6. 실제 DB 백업을 임시 DB에 복원해 원본과 비교한 뒤 적용했습니다. 기존 29개 테이블을 검사했고 기존 소유권은 유지했으며, 암묵적 로컬 소유권 4건만 명시적으로 추가했습니다.

**검증 근거:** 다이어리 구조·로그인·DB 권한 관련 격리 검증 20개 통과. 격리 DB·임시 역할에서 회원 간 조회/수정 차단, 검색 계정의 인증 자료 조회 거부, 실행 계정의 DROP/TRUNCATE/DDL/서버 파일 읽기 거부, 연결 풀 소유자 초기화, 악성 상품 문구의 데이터 처리, 임베딩 저장을 검증합니다. 로그인/다이어리 구조 검증도 함께 실행합니다. 실제 모델 추론이나 브라우저 기능 테스트를 대신하는 검증은 아닙니다.

**운영 적용:** 로컬 서버를 재시작해 실행 역할 3개 모두 고권한 플래그가 없는 것과 FORCE RLS 12개를 확인했습니다. API·검색 서버·로컬 관리자 조회가 응답하고, 검색 모델이 로드되며, 소유자용 키로 검색 서버에 접근하면 거부되는 것을 확인했습니다. 백업·비밀번호·개인 데이터·로컬 TODO는 Git에 포함하지 않습니다.

**1차 완료 시 남은 위험:** 당시 프로세스의 파일 접근은 OS 수준으로 격리하지 않았습니다. 검색·크롤러 경계는 아래 2차 작업에서 보완했습니다. API 서버를 완전히 장악한 공격자가 소유자 컨텍스트를 임의 설정하는 상황까지 RLS만으로 막을 수는 없습니다. 별도 OS 계정/컨테이너·파일 마운트·네트워크 제한, 암호화된 외부 백업·주기적 복원·보안 경보는 후속 작업입니다.

## 발표 시 구분할 완료 상태

| 상태 | 내용 |
| --- | --- |
| 구현 및 배포 | 웹 화면, 스티커/폴라로이드 편집, 자이로 연동, 상품 연결, DB 구조, 소셜 로그인 코드 |
| 로컬 적용 확인 | PostgreSQL·pgvector, SAM 2/YOLO 모델 준비, 검색 모델 로드, DB 데이터 이관, 역할 분리·RLS·백업 복원 |
| 사용자 확인 필요 | 모바일 편집·실제 사진 검색/생성 결과·자이로 표현·구글/카카오 실제 로그인 왕복 |
| 외부 설정 필요 | 구글·카카오 개발자 앱의 키와 콜백 등록. 실제 쇼핑 API 이용 가능 여부와 제공자 자격 증명 |
| 미구현/후속 | GPS 근접 알림, 계정 연결·회원 탈퇴, GPU API OS 격리·보관기간 정책 |

네이버 쇼핑 API는 서비스 종료 확인에 따라 현재 직접 상품 링크 연결로 처리하며, 정상 검색 API가 연결된 것으로 발표하지 않습니다. 현재 상품 검색은 제공자 설정과 공식몰 접근 가능 여부에 따라 결과가 달라집니다.

## 다음 기록에 포함할 항목

날짜, 해결하려던 문제, 최종 구현·변경 내용, 영향을 받는 파일/기능, 검증 결과, 로컬 적용과 배포 여부, 남은 확인 사항, 커밋/PR 근거를 함께 기록합니다. 완료되지 않은 작업을 완료로 표시하지 않습니다. 개인용 체크리스트는 Git에서 제외된 루트 `TODO.md`에 유지합니다.


## 2026-11-27 검색·크롤러 보안 강화 2차

**문제:** DB 권한은 나눴지만 검색·크롤러가 Windows 사용자로 실행되어 프로세스 침해 시 회원 파일·관리자 키·내부망 접근 가능성이 남았습니다.

**구현:** 검색·크롤러·외부 통신 게이트웨이를 로컬 Docker 컨테이너로 분리했습니다. 최소 파일 마운트, 비루트·권한 제거·읽기 전용 루트, 기본 거부 방화벽, 공인 IP를 검증하는 도메인 제한 HTTPS 게이트웨이를 추가했습니다. 크롤러는 DB·회원 사진을 받지 않으며 Chromium 자체 샌드박스와 작업·응답·자원 제한을 유지합니다. 시작/종료/이미지 갱신 및 중첩된 키의 유출 검사도 변경했습니다.

**검증:** 기존 20개 + 신규 22개, 총 42개 통과. 실제 컨테이너에서 파일·쓰기·UID/capability 및 금지 통신 차단, 검색 DB와 크롤러 인증, 허용 공개 robots.txt HTTPS HEAD 200, 샌드박스 활성 Chromium 빈 페이지 실행, 검색 모델 로드, 기존 API 응답을 확인했습니다. 사진 추론·실제 상품 수집·모바일 UI는 사용자 확인 대상으로 유지합니다.

**로컬 적용:** 네이티브 검색을 격리 스택으로 전환했습니다. 기존 약 1.5GB 모델을 읽기 전용으로 재사용하고 DB 데이터/비밀번호를 유지했습니다. EmbeddingGemma 2는 로컬 CPU, SAM 2·YOLO는 기존 GPU API에서 실행합니다. 코드 근거: [a6da64a](https://github.com/niraaah/GoodMorNing/commit/a6da64a), [PR #9](https://github.com/niraaah/GoodMorNing/pull/9). 자동 검사·병합·배포 결과는 해당 PR과 연결된 Actions에서 확인합니다.

**파일:** `containers/search/`, `server/goods/crawler_service.py`, 검색·수집 코드, `scripts/search_sandbox.py`, 설치/시작/종료 스크립트, `scripts/verify_search_sandbox.py`, `server/test_search_isolation.py`, CI·비밀 검사·README.

**남은 범위:** GPU API 자체 OS 격리, Docker/호스트 관리 권한, 허용 판매처를 통한 유출 가능성, 썸네일 총량 제한, 보안 경보·암호화 외부 백업은 별도 과제입니다. 간접 프롬프트 공격을 완전히 제거했다고 표현하지 않습니다. [보안 설계 및 상세 검증](SECURITY.md#검색크롤러-컨테이너-격리-2차).
