# 구글·카카오·네이버 로그인 설정

회원 가입과 로그인은 구글·카카오·네이버만 지원합니다. 자체 아이디·비밀번호는 받거나 저장하지 않습니다. 네이버 쇼핑 검색과 로그인 설정은 별개입니다.

## 집에서 키 넣을 파일

`C:\Users\meer\Downloads\goodmorning\data\auth.local.json`

이 PC에는 빈 설정 파일을 준비합니다. 다른 PC에서는 `server/auth.example.json`을 위 경로로 복사하세요. 키는 다음 항목의 빈 따옴표 안에 넣습니다. `data/`와 `*.local.json`은 Git에서 제외되며, 프론트엔드/Pages/Actions 변수에 키를 넣지 않습니다.

| 항목 | 넣을 값 |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Google Auth Platform의 웹 애플리케이션 OAuth 클라이언트 ID |
| `GOOGLE_CLIENT_SECRET` | 같은 클라이언트의 보안 비밀번호(Client secret) |
| `KAKAO_CLIENT_ID` | 카카오 앱의 **REST API 키** |
| `KAKAO_CLIENT_SECRET` | 카카오 로그인 Client Secret (활성화 필요) |
| `NAVER_LOGIN_CLIENT_ID` | 네이버 로그인 애플리케이션 Client ID |
| `NAVER_LOGIN_CLIENT_SECRET` | 같은 애플리케이션 Client Secret |

콜백 주소 세 항목은 이미 입력되어 있으니 그대로 둡니다. 파일 저장 후 앱을 새로고침하면 서버가 설정을 다시 읽습니다. 환경변수를 설정해 둔 경우에는 환경변수가 파일보다 우선하며 서버 재시작이 필요합니다.

## 개발자 콘솔 등록

서비스 URL: `https://niraaah.github.io/GoodMorNing/`

- Google: OAuth 동의 화면을 구성하고 **웹 애플리케이션** 클라이언트를 생성합니다. 승인된 리디렉션 URI에 `https://niraaah.github.io/GoodMorNing/auth/google.html`을 정확히 등록하세요. 테스트 모드라면 사용할 구글 계정을 테스트 사용자로 추가합니다. 요청 범위는 `openid`이며 소셜 이름·이메일·프로필 사진을 회원 정보로 가져오지 않습니다.
- Kakao: 앱을 만들고 카카오 로그인을 활성화합니다. 웹 사이트 도메인에 `https://niraaah.github.io`를 등록하고, Redirect URI에 `https://niraaah.github.io/GoodMorNing/auth/kakao.html`을 등록하세요. 추가 닉네임·프로필 사진·이메일 동의항목을 요청하지 않도록 콘솔 설정을 확인하고 Client Secret을 발급·활성화합니다. JavaScript 키나 Admin 키가 아닌 REST API 키를 사용하세요. 앱 공개 전에는 테스트 가능한 팀원 계정인지 확인합니다.

공식 안내: [Google 웹 서버 OAuth](https://developers.google.com/identity/protocols/oauth2/web-server), [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect), [Kakao REST 로그인](https://developers.kakao.com/docs/ko/kakaologin/rest-api).

## 동작과 남은 확인

- 로그인 버튼은 홈·다이어리·훔쳐보기 상단 및 에셋함 상단에 있습니다. 키가 없는 서비스는 `준비 중`으로 표시됩니다. 공개 웹 주소에서 같은 탭으로 로그인하며 PC의 API·DB·터널이 켜져 있어야 합니다.
- 첫 가입 시 방문자 자료 가져오기를 선택하면 해당 소유권을 회원 계정에 연결하고 이전 방문자 토큰은 무효화합니다. 이미 가입한 계정에는 방문자 자료를 자동 합치지 않습니다. PC 관리자 자료도 자동으로 옮기지 않습니다.
- 구글·카카오·네이버는 각각 별도 계정입니다. 이메일이나 이름이 같아도 자동 연결하지 않습니다. 계정 연결은 지원하지 않습니다. 첫 로그인 프로필 설정과 계정설정·탈퇴는 아래와 같이 지원합니다.
- 서버에는 서비스별 사용자 ID, 직접 정한 닉네임, 선택 프로필 사진, 동의 버전·시각, 세션 해시를 저장합니다. 제공자 액세스 토큰은 연결 해제용으로 최대 10분 동안 RAM에만 보관합니다. 앱 세션은 브라우저 탭 저장소에만 보관하며 최대 7일, 24시간 미사용 시 만료되고 로그아웃 즉시 폐기됩니다.
- OAuth state는 브라우저 검증값·서비스·설정·출처에 결합하고 10분 내 한 번만 사용합니다. 제공자 토큰 교환은 로컬 API에서 수행합니다. 인증 코드가 돌아오는 정적 페이지에는 외부 스크립트가 없고 쿼리를 즉시 지웁니다.
- 로그인 DB 추가 전 로컬 백업을 남깁니다. 조회 전용 DB 화면에는 인증 세션 및 OAuth 시도 테이블을 공개하지 않습니다.
- 실제 구글·카카오·네이버 왕복 로그인은 키 등록 후 사용자가 확인해야 합니다. 구현/빌드/격리된 보안 검증 통과가 실제 제공자 로그인 완료를 뜻하지 않습니다.


## 프로필·설정·탈퇴

첫 소셜 로그인 후 닉네임(2~20자)을 정하고 약관·개인정보 안내·만 14세 이상을 확인합니다. 사진은 선택이며 기본 이미지로도 가입할 수 있습니다. 기존 회원도 현재 프로필·약관 확인 전에는 개인 자료 API를 사용할 수 없습니다. 기존 자료가 없어지지는 않습니다.

상단 내 계정에서 사진 변경/기본 이미지 복원, 닉네임 변경, 로그아웃, 회원탈퇴를 지원합니다. 사진은 2MB 이하 JPG/PNG/WebP 정지 이미지이며 256px JPEG로 재생성해 메타데이터를 제거합니다. 다시 로그인해도 직접 정한 이름은 유지됩니다.

탈퇴는 소셜 로그인 후 10분 안에 닉네임(설정 전에는 회원탈퇴)을 입력하고 삭제 범위를 확인해야 합니다. 진행 중인 작업이 있으면 완료 후 다시 요청합니다. 전체 회원 세션·위치 공유 차단, 개인 파일·행 삭제, 실패 재시도와 관리 백업 7일 보존을 적용합니다. 소셜 연결 해제는 최신 메모리 토큰으로 시도하며 실패·서버 재시작 등으로 불가능하면 제공자 설정에서 해제하도록 안내합니다. 소셜 계정 자체를 삭제하지 않습니다.

운영자 Team GoodGeeks / 문의 goodgeeks.info@gmail.com. [이용약관](TERMS.md), [개인정보 처리방침](PRIVACY.md), [공개 운영 전 확인](LEGAL_REVIEW.md). 키·콜백 설정 후 첫 로그인, 사진 선택 없이 가입, 이름/사진 변경, 재로그인 후 유지, 계정별 자료 분리, 재인증 및 탈퇴·제공자 연결 해제를 사용자가 확인합니다.


## 네이버 로그인 등록 (PC 웹·Mobile 웹 공통)

| 입력란 | 입력값 |
| --- | --- |
| 서비스 URL | `https://niraaah.github.io/GoodMorNing/` |
| Callback URL | `https://niraaah.github.io/GoodMorNing/auth/naver.html` |

사용 API에서 **네이버 로그인**을 선택합니다. 회원 정보 제공 항목은 애플리케이션별 식별자만 사용하며 이름·이메일·별명·프로필 사진·전화번호·생년월일 등 추가 항목은 선택하지 않습니다. 굿모닝 닉네임과 선택 프사는 가입 후 직접 설정합니다. OIDC 옵션을 추가로 켜지 않는 일반 OAuth 코드 방식입니다. 서비스 검수 전에는 개발자센터에서 허용한 테스트 계정으로 확인하고, 일반 이용자 공개에는 네이버 검수 조건을 확인하세요.

발급된 값은 `data/auth.local.json`의 `NAVER_LOGIN_CLIENT_ID`, `NAVER_LOGIN_CLIENT_SECRET`에만 입력합니다. `NAVER_LOGIN_CALLBACK_URL`은 위 주소가 기본값입니다. **쇼핑 검색의 NAVER_CLIENT_ID/SECRET과 별개의 설정**이며 서로 복사하지 않습니다. 기존 구글·카카오 항목을 지우거나 파일 전체를 예제로 덮어쓰지 마세요. 키 값은 Git·Pages·Actions·채팅에 넣지 않습니다. 파일 저장 후 앱을 새로고침하면 다시 읽습니다.

네이버 state·브라우저 verifier·Origin·제공자·설정 바인딩을 확인한 뒤 서버가 code를 교환합니다. 성공 코드 00의 response.id만 회원 식별에 사용하고 기타 프로필은 저장하지 않습니다. 제공자 access token은 탈퇴 연결 해제를 위해 최대 10분 RAM에만 보관합니다. 탈퇴 시 `/oauth2.0/revoke`를 호출하고 실패하거나 토큰이 없으면 연결 해제를 확인하지 못했다고 안내합니다. 제공자 계정 자체를 삭제하지 않습니다. 네이버 사이트에서 먼저 연결을 끊는 이벤트를 수신하는 webhook은 별도 후속 범위입니다.

공식 근거: [등록 및 OAuth·토큰 폐기](https://developers.naver.com/docs/login/devguide/devguide.md), [프로필 응답](https://developers.naver.com/docs/login/profile/profile.md), [공식 버튼 자산](https://developers.naver.com/docs/login/bi/bi.md).
