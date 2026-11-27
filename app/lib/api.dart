import 'dart:async';
import 'dart:js_interop';
import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:web/web.dart' as web;

class Api {
  static String base = const String.fromEnvironment('API_BASE');
  static String token = '';
  static bool _automaticReady = false;
  static bool _explicitConnection = false;
  static final _images = <String, Future<Uint8List>>{};
  static bool get hosted => Uri.base.host.endsWith('github.io');
  static bool get configured => base.isNotEmpty || !hosted;
  static Map<String, String> get headers =>
      token.isEmpty ? {} : {'Authorization': 'Bearer $token'};
  static void clearAfterWithdrawal() {
    web.window.localStorage.setItem('goodmorning-clear-browser', '1');
    token = '';
    _images.clear();
    web.window.sessionStorage.removeItem('goodmorning-token');
    web.window.sessionStorage.removeItem('goodmorning-oauth');
  }

  static Future<void> initialize() async {
    if (web.window.localStorage.getItem('goodmorning-clear-browser') == '1') {
      for (final storage in [
        web.window.localStorage,
        web.window.sessionStorage,
      ]) {
        final keys = <String>[];
        for (var i = 0; i < storage.length; i++) {
          final key = storage.key(i);
          if (key != null &&
              key.startsWith('goodmorning-') &&
              key != 'goodmorning-clear-browser')
            keys.add(key);
        }
        for (final key in keys) {
          storage.removeItem(key);
        }
      }
      for (final database in [
        'goodmorning-diary-demo',
        'goodmorning-3d-post',
        'goodmorning-sticker-library',
      ]) {
        final completed = Completer<void>();
        final request = web.window.indexedDB.deleteDatabase(database);
        request.addEventListener(
          'success',
          ((web.Event _) {
            if (!completed.isCompleted) completed.complete();
          }).toJS,
        );
        void failed(web.Event _) {
          if (!completed.isCompleted)
            completed.completeError(
              Exception('브라우저 저장 정보 삭제가 지연되고 있어요. 다른 굿모닝 탭을 모두 닫고 새로고침해 주세요.'),
            );
        }

        request.addEventListener('error', failed.toJS);
        request.addEventListener('blocked', failed.toJS);
        await completed.future.timeout(const Duration(seconds: 15));
      }
    }
    web.window.localStorage.removeItem('goodmorning-clear-browser');
    base = web.window.localStorage.getItem('goodmorning-api') ?? base;
    token = web.window.sessionStorage.getItem('goodmorning-token') ?? '';
    final fragment = Uri.splitQueryString(Uri.base.fragment);
    if (fragment.containsKey('server')) {
      _explicitConnection = true;
      configure(fragment['server']!, fragment['key'] ?? '');
      web.window.history.replaceState(
        null,
        '',
        '${Uri.base.path}${Uri.base.hasQuery ? '?${Uri.base.query}' : ''}',
      );
    }
  }

  static Future<void> autoConnect() async {
    if (!hosted || _automaticReady || _explicitConnection) return;
    final configResponse = await http
        .get(
          staticUri('runtime-config.json').replace(
            queryParameters: {
              'v': DateTime.now().millisecondsSinceEpoch.toString(),
            },
          ),
        )
        .timeout(const Duration(seconds: 15));
    if (configResponse.statusCode != 200)
      throw Exception('자동 연결 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.');
    final config = jsonDecode(configResponse.body) as Map<String, dynamic>;
    final address = config['apiBase'] as String? ?? '';
    if (address.isEmpty) throw Exception('GPU 서버 주소가 아직 배포되지 않았어요.');
    final visitorToken =
        web.window.localStorage.getItem('goodmorning-visitor-token') ?? '';
    // Restore an unclaimed visitor collection after an expired member session.
    // Do not overwrite that collection's capability with a new guest token.
    for (final candidate in {
      token,
      visitorToken,
    }.where((value) => value.isNotEmpty)) {
      configure(address, candidate);
      final response = await http
          .get(uri('/auth/me'), headers: headers)
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 200) {
        _automaticReady = true;
        return;
      }
      if (![401, 403].contains(response.statusCode))
        throw Exception('PC의 GPU 서버가 응답하지 않아요. 잠시 후 다시 시도해 주세요.');
    }
    configure(address, '');
    final response = await http
        .post(uri('/auth/guest'))
        .timeout(const Duration(seconds: 20));
    final result = check(response) as Map<String, dynamic>;
    token = result['token'] as String;
    web.window.localStorage.setItem('goodmorning-visitor-token', token);
    web.window.sessionStorage.setItem('goodmorning-token', token);
    _automaticReady = true;
  }

  static void configure(String server, String key) {
    final parsed = Uri.tryParse(server.trim());
    if (parsed == null ||
        !parsed.hasAuthority ||
        !(parsed.scheme == 'https' ||
            parsed.scheme == 'http' &&
                ['localhost', '127.0.0.1'].contains(parsed.host)) ||
        parsed.userInfo.isNotEmpty ||
        parsed.hasQuery ||
        parsed.hasFragment ||
        !['', '/'].contains(parsed.path)) {
      throw const FormatException('https://로 시작하는 서버 주소를 입력해 주세요.');
    }
    base = parsed.origin;
    token = key.trim();
    _images.clear();
    web.window.localStorage.setItem('goodmorning-api', base);
    web.window.sessionStorage.setItem('goodmorning-token', token);
  }

  static void useManualConnection(String server, String key) {
    configure(server, key);
    _explicitConnection = true;
  }

  static Future<void> socialLogin(
    String provider,
    bool keepGuest,
    String policyVersion,
    bool terms,
    bool privacy,
    bool age14,
  ) async {
    if (!['google', 'kakao'].contains(provider))
      throw Exception('지원하지 않는 로그인 방식이에요.');
    final providers = await get('/auth/providers');
    final callback = Uri.parse(providers[provider]['callback_url'] as String);
    if (callback.origin != Uri.base.origin)
      throw Exception('공개 웹 주소에서 로그인을 이용해 주세요.');
    final result = await post('/auth/$provider/start', {
      'keep_guest': keepGuest,
      'policy_version': policyVersion,
      'terms': terms,
      'privacy': privacy,
      'age14': age14,
    });
    web.window.sessionStorage.setItem(
      'goodmorning-oauth',
      jsonEncode({
        'provider': provider,
        'state': result['state'],
        'verifier': result['verifier'],
        'server': uri('/').origin,
        'guestToken': token.startsWith('guest.') ? token : '',
        'expires': DateTime.now().millisecondsSinceEpoch + 600000,
      }),
    );
    web.window.location.assign(result['authorize_url'] as String);
  }

  static Future<void> logout() async {
    await post('/auth/logout');
    web.window.sessionStorage.removeItem('goodmorning-token');
    web.window.sessionStorage.removeItem('goodmorning-oauth');
    web.window.location.reload();
  }

  static Uri staticUri(String path) {
    final uri = Uri.base.resolve(path);
    final revision = web.document.documentElement?.getAttribute('data-build');
    return revision == null
        ? uri
        : uri.replace(
            queryParameters: {...uri.queryParameters, '_build': revision},
          );
  }

  static Future<Uint8List> image(String path) =>
      _images.putIfAbsent(path, () async {
        final response = await http
            .get(uri(path), headers: headers)
            .timeout(const Duration(seconds: 30));
        if (response.statusCode != 200) {
          _images.remove(path);
          throw Exception('이미지를 불러오지 못했어요.');
        }
        return response.bodyBytes;
      });
  static Uri uri(String path) =>
      Uri.parse('${base.isEmpty ? Uri.base.origin : base}$path');
  static dynamic check(http.Response response) {
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw Exception('GPU 서버 연결에서 주소와 접근 키를 확인해 주세요.');
    }
    final dynamic data;
    try {
      data = jsonDecode(utf8.decode(response.bodyBytes));
    } catch (_) {
      throw Exception('서버 주소를 확인해 주세요. API 응답이 아닙니다.');
    }
    if (response.statusCode >= 400) {
      throw Exception(
        data is Map && data['detail'] is String
            ? data['detail']
            : '요청을 처리하지 못했어요. (${response.statusCode})',
      );
    }
    return data;
  }

  static Future<dynamic> get(String path) async => check(
    await http
        .get(uri(path), headers: headers)
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> save(Map<String, dynamic> diary) async => check(
    await http
        .put(
          uri('/api/diaries/${diary['id']}'),
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(diary),
        )
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> post(
    String path, [
    Map<String, dynamic> body = const {},
  ]) async => check(
    await http
        .post(
          uri(path),
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> upload(
    String path,
    Uint8List bytes,
    String filename,
    Map<String, String> fields,
  ) async {
    final request = http.MultipartRequest('POST', uri(path))
      ..headers.addAll(headers)
      ..fields.addAll(fields)
      ..files.add(
        http.MultipartFile.fromBytes('photo', bytes, filename: filename),
      );
    return check(
      await http.Response.fromStream(
        await request.send().timeout(const Duration(seconds: 60)),
      ),
    );
  }
}
