# 구글·카카오 로그인 설정

회원 가입과 로그인은 구글·카카오만 지원합니다. 자체 아이디·비밀번호는 받거나 저장하지 않습니다. 네이버 쇼핑 검색과 로그인 설정은 별개입니다.

## 집에서 키 넣을 파일

`C:\Users\meer\Downloads\goodmorning\data\auth.local.json`

이 PC에는 빈 설정 파일을 준비합니다. 다른 PC에서는 `server/auth.example.json`을 위 경로로 복사하세요. 키는 다음 항목의 빈 따옴표 안에 넣습니다. `data/`와 `*.local.json`은 Git에서 제외되며, 프론트엔드/Pages/Actions 변수에 키를 넣지 않습니다.

| 항목 | 넣을 값 |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Google Auth Platform의 웹 애플리케이션 OAuth 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 같은 클라이언트의 보안 비밀번호(Client secret) |
| `KAKAO_CLIENT_ID` | 카카오 앱의 **REST API 키** |
| `KAKAO_CLIENT_SECRET` | 카카오 로그인 Client Secret (활성화 필요) |

콜백 주소 두 항목은 이미 입력되어 있으니 그대로 둡니다. 파일 저장 후 앱을 새로고침하면 서버가 설정을 다시 읽습니다. 환경변수를 설정해 둔 경우에는 환경변수가 파일보다 우선하며 서버 재시작이 필요합니다.

## 개발자 콘솔 등록

서비스 URL: `https://niraaah.github.io/GoodMorNing/`

- Google: OAuth 동의 화면을 구성하고 **웹 애플리케이션** 클라이언트를 생성합니다. 승인된 리디렉션 URI에 `https://niraaah.github.io/GoodMorNing/auth/google.html`을 정확히 등록하세요. 테스트 모드라면 사용할 구글 계정을 테스트 사용자로 추가합니다. 요청 범위는 `openid profile`이며 이메일은 수집하지 않습니다.
- Kakao: 앱을 만들고 카카오 로그인을 활성화합니다. 웹 사이트 도메인에 `https://niraaah.github.io`를 등록하고, Redirect URI에 `https://niraaah.github.io/GoodMorNing/auth/kakao.html`을 등록하세요. 닉네임(`profile_nickname`) 동의항목을 설정하고 Client Secret을 발급·활성화합니다. JavaScript 키나 Admin 키가 아닌 REST API 키를 사용하세요. 앱 공개 전에는 테스트 가능한 팀원 계정인지 확인합니다.

공식 안내: [Google 웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect), [Kakao REST 로그인](https://developers.kakao.com/docs/ko/kakaologin/rest-api).

## 동작과 남은 확인

- 로그인 버튼은 홈·다이어리·훔쳐보기 상단 및 에셋함 상단에 있습니다. 키가 없는 서비스는 `준비 중`으로 표시됩니다. 공개 웹 주소에서 같은 탭으로 로그인하며 PC의 API·DB·터널이 켜져 있어야 합니다.
- 첫 가입 시 방문자 자료 가져오기를 선택하면 해당 소유권을 회원 계정에 연결하고 이전 방문자 토큰은 무효화합니다. 이미 가입한 계정에는 방문자 자료를 자동 합치지 않습니다. PC 관리자 자료도 자동으로 옮기지 않습니다.
- 구글과 카카오는 별도 계정입니다. 이메일이나 이름이 같아도 자동 연결하지 않습니다. 계정 연결·회원 탈퇴 기능은 이번 범위에 포함되지 않습니다.
- 서버에는 서비스별 사용자 ID, 표시 이름, 세션 해시를 저장합니다. 제공자 액세스 토큰은 프로필 확인 후 보관하지 않습니다. 앱 세션은 브라우저 탭 저장소에만 보관하며 최대 7일, 24시간 미사용 시 만료되고 로그아웃 즉시 폐기됩니다.
- OAuth state는 브라우저 검증값·서비스·설정·출처에 결합하고 10분 내 한 번만 사용합니다. 제공자 토큰 교환은 로컬 API에서 수행합니다. 인증 코드가 돌아오는 정적 페이지에는 외부 스크립트가 없고 쿼리를 즉시 지웁니다.
- 로그인 DB 추가 전 로컬 백업을 남깁니다. 조회 전용 DB 화면에는 인증 세션 및 OAuth 시도 테이블을 공개하지 않습니다.
- 실제 구글·카카오 왕복 로그인은 키 등록 후 사용자가 확인해야 합니다. 구현/빌드/격리된 보안 검증 통과가 실제 제공자 로그인 완료를 뜻하지 않습니다.
