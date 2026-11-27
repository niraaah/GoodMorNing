# 브랜치와 배포

- `main`: 검증 후 병합하는 배포 브랜치. GitHub Pages는 이 브랜치에서 배포한다.
- `niraaah`: 새 기능·오류 수정·운영 작업을 진행하는 고정 개발 브랜치. 병합 후에도 유지한다.
- 작업 전에 최신 `origin/main`을 `niraaah`에 병합하고, 변경을 커밋·push한 뒤 `main` 대상 PR을 연다. main에 직접 커밋하지 않으며, 사용자 요청 없이 주제별 브랜치를 추가하지 않는다.
- PR에는 변경 이유, 확인한 항목, 실사용 확인이 남은 항목을 적는다. 빌드·민감정보 검사를 통과한 뒤 병합한다. 다음 작업 전 `niraaah`를 다시 main과 동기화한다. 진행 중인 변경을 강제로 덮어쓰지 않는다.
- GitHub Pages 배포와 PC의 실행 환경 전환은 별도다. DB를 바꿀 때는 기존 데이터 백업·이관 검증 후 서버를 재시작한다.

```powershell
git fetch origin
git switch niraaah
git merge origin/main
# 수정 및 확인
git add <변경한 파일>
git commit -m "Describe the change"
git push origin niraaah
gh pr create --base main --head niraaah
```

커밋 훅의 민감정보 검사는 끄지 않는다. API 키·DB 비밀번호·사용자 데이터·백업·로컬 TODO는 커밋하지 않는다. 실제 휴대폰·브라우저 기능 확인은 사용자 테스트 범위를 따른다.
