import 'package:material_ui/material_ui.dart';
import 'api.dart';

class AccountDialog extends StatefulWidget {
  const AccountDialog({super.key});
  @override
  State<AccountDialog> createState() => _AccountDialogState();
}

class _AccountDialogState extends State<AccountDialog> {
  Map<String, dynamic>? account, providers;
  bool busy = false, keepGuest = false;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      await Api.autoConnect();
      final values = await Future.wait([
        Api.get('/auth/me'),
        Api.get('/auth/providers'),
      ]);
      if (mounted)
        setState(() {
          account = Map<String, dynamic>.from(values[0]);
          providers = Map<String, dynamic>.from(values[1]);
        });
    } catch (_) {
      if (mounted) setState(() => error = '로그인 정보를 불러오지 못했어요. 서버 연결을 확인해 주세요.');
    }
  }

  Future<void> login(String provider) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.socialLogin(provider, keepGuest);
    } catch (e) {
      if (mounted)
        setState(() {
          busy = false;
          error = e.toString().replaceFirst('Exception: ', '');
        });
    }
  }

  Future<void> logout() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.logout();
    } catch (_) {
      if (mounted)
        setState(() {
          busy = false;
          error = '로그아웃하지 못했어요. 연결 후 다시 시도해 주세요.';
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final member = account?['kind'] == 'member';
    return AlertDialog(
      title: Text(member ? '내 계정' : '내 수집방 로그인'),
      content: SizedBox(
        width: 340,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (account == null && error == null)
                const Center(child: CircularProgressIndicator()),
              if (member) ...[
                Text('${account!['name']}님'),
                const SizedBox(height: 12),
                const Text('로그아웃해도 계정에 저장한 에셋과 다이어리는 남아 있어요.'),
                const SizedBox(height: 20),
                OutlinedButton(
                  onPressed: busy ? null : logout,
                  child: const Text('로그아웃'),
                ),
              ] else if (providers != null) ...[
                const Text('구글 또는 카카오 계정으로 나의 에셋과 다이어리를 이어서 사용해 보세요.'),
                const SizedBox(height: 16),
                for (final provider in ['google', 'kakao'])
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: OutlinedButton(
                      onPressed:
                          !busy && providers![provider]?['enabled'] == true
                          ? () => login(provider)
                          : null,
                      style: OutlinedButton.styleFrom(
                        backgroundColor: provider == 'kakao'
                            ? const Color(0xfffee500)
                            : Colors.white,
                        foregroundColor: const Color(0xff1f1f1f),
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: Text(
                        '${provider == 'google' ? 'Google 계정으로 로그인' : '카카오 로그인'}${providers![provider]?['enabled'] == true ? '' : ' · 준비 중'}',
                      ),
                    ),
                  ),
                if (account?['kind'] == 'guest') ...[
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: keepGuest,
                    onChanged: busy
                        ? null
                        : (value) => setState(() => keepGuest = value ?? false),
                    title: const Text(
                      '처음 가입할 때 현재 방문자 자료 가져오기',
                      style: TextStyle(fontSize: 14),
                    ),
                  ),
                  const Text(
                    '이미 가입한 계정에는 합쳐지지 않아요. 구글과 카카오 계정은 각각 별도의 수집방으로 연결돼요.',
                    style: TextStyle(fontSize: 12),
                  ),
                ],
              ],
              if (busy)
                const Padding(
                  padding: EdgeInsets.only(top: 16),
                  child: LinearProgressIndicator(),
                ),
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 16),
                  child: Text(
                    error!,
                    style: const TextStyle(color: Colors.red),
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: busy ? null : () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    );
  }
}
