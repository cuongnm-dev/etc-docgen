# ref-stack-react-native.md — React Native

## Directory Tree
```
{name}/
  src/
    screens/      HomeScreen.tsx | {Feature}Screen.tsx
    navigation/   RootNavigator.tsx | types.ts
    components/   shared UI components
    hooks/        use*.ts
    services/     API clients
    stores/       Zustand stores
    types/
    assets/       images/ | fonts/
  android/
  ios/
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  package.json | tsconfig.json | app.json | metro.config.js | biome.json
```

## Starter Code

**`src/screens/HomeScreen.tsx`**
```tsx
import { StyleSheet, Text, View } from 'react-native'

export default function HomeScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>PROJECT_NAME</Text>
    </View>
  )
}
// Replace PROJECT_NAME with actual project name when scaffolding

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: 'bold' },
})
```

**`src/navigation/RootNavigator.tsx`**
```tsx
import { NavigationContainer } from '@react-navigation/native'
import { createNativeStackNavigator } from '@react-navigation/native-stack'
import HomeScreen from '../screens/HomeScreen'

const Stack = createNativeStackNavigator()

export default function RootNavigator() {
  return (
    <NavigationContainer>
      <Stack.Navigator>
        <Stack.Screen name="Home" component={HomeScreen} />
      </Stack.Navigator>
    </NavigationContainer>
  )
}
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: React Native conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (React Native)
## Rules
- `StyleSheet.create()` always — no inline style objects (GC pressure).
- `Platform.OS` for platform divergence — no platform-specific files unless significant.
- Navigation: React Navigation with typed routes. No manual URL routing.
- State: Zustand (client), TanStack Query (server). No Redux.
- Hooks in `hooks/`, screens in `screens/`, navigation in `navigation/`.
## Anti-patterns
No inline styles | No `any` | No business logic in screens
```

## `.env.example`
```bash
API_URL=http://localhost:3000
```

## `.gitignore`
```
node_modules/
.expo/
android/build/
ios/build/
ios/Pods/
.env
*.log
.DS_Store
```

## Scaffold command
```bash
pnpm dlx react-native@latest init {Name} --template react-native-template-typescript
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test`
