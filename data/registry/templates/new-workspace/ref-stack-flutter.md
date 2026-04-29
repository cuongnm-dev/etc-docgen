# ref-stack-flutter.md — Flutter

## Directory Tree
```
{name}/
  lib/
    features/
      home/       home_screen.dart | home_controller.dart
    core/
      router/     app_router.dart
      theme/      app_theme.dart
      network/    api_client.dart
      di/         injection.dart
    shared/
      widgets/    common_widgets.dart
      utils/      formatters.dart
  test/
  android/ | ios/ | web/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .env.example | .gitignore | README.md | CLAUDE.md
  pubspec.yaml | analysis_options.yaml
```

## Starter Code

**`lib/main.dart`**
```dart
import 'package:flutter/material.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '{project-name}',
      theme: ThemeData(colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue), useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('{project-name}')),
      body: const Center(child: Text('Hello from {project-name}', style: TextStyle(fontSize: 24))),
    );
  }
}
```

**`analysis_options.yaml`**
```yaml
include: package:flutter_lints/flutter.yaml
linter:
  rules:
    - prefer_const_constructors
    - prefer_const_widgets
    - avoid_print
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Flutter conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Flutter)
## Rules
- Feature-first folder structure: `lib/features/{feature}/`.
- Widgets are immutable — state lives in State objects or providers (Riverpod/BLoC).
- `const` constructors everywhere possible — critical for performance.
- Use `flutter_lints` analysis_options. No `print()` — use `debugPrint` or logger.
- Navigation: `go_router` for declarative routing.
- State: Riverpod (recommended) or BLoC. No setState beyond widget-local ephemeral state.
## Anti-patterns
No `print()` in production | No setState for shared state | No business logic in build()
```

## `.env.example`
```bash
# Flutter uses --dart-define for environment variables:
# flutter run --dart-define=API_URL=https://api.example.com
API_URL=http://localhost:3000
```

## `.gitignore`
```
.dart_tool/
.packages
build/
*.iml
*.lock
android/.gradle/
ios/Pods/
.env
.DS_Store
```

## Scaffold command
```bash
flutter create {name}
cd {name}
flutter pub add flutter_lints go_router riverpod flutter_riverpod
```

## Verification
`flutter analyze` → `flutter test` → `flutter build apk --debug`
