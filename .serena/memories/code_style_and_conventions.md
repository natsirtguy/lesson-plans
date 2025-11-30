# Code Style and Conventions

## Python Code Style

### General Style
- Standard Python 3 conventions
- Clear, descriptive variable names
- Comments for clarity (but code should be self-documenting)
- No type hints used (simple scripts)
- No docstrings required for simple functions

### Data Structures
- Dictionaries for category-based data
- Lists for ordered collections
- JSON for data interchange

### Example from convert_topics.py
```python
# Simple function with clear purpose
def convert_topics():
    """Convert Python dictionaries to JSON data structure."""
    
    # Clear variable names
    arts_topics = []
    knowledge_topics = []
    
    # Descriptive dictionary keys
    data = {
        "masterLists": {...},
        "queues": {...}
    }
```

## HTML/JavaScript Style

### Alpine.js Patterns
- Use `x-data` for component state
- Use `x-init` for initialization
- Use `x-show` for conditional rendering
- Use `@click` for event handlers

### Example Patterns
```html
<!-- Reactive component -->
<body x-data="lessonPlanApp()" x-init="init()">

<!-- Event handling -->
<button @click="exportData(); showMenu = false">

<!-- Conditional display -->
<div x-show="showMenu" x-transition>
```

### Tailwind CSS
- Inline utility classes
- Mobile-first responsive design
- Touch-friendly sizing (minimum 44px buttons)
- Consistent spacing with Tailwind scale

### Button Patterns
```html
<button class="w-full px-4 py-3 bg-blue-500 text-white rounded-lg 
               hover:bg-blue-600 active:bg-blue-700 btn-touch">
```

## File Organization

### Clear Separation
- `/docs` - Deployable PWA application
- Root - Development tools and documentation
- `/planning` - Research and design docs

### File Naming
- Lowercase with hyphens: `initial-data.json`
- Python: snake_case: `convert_topics.py`
- Markdown: uppercase for docs: `README.md`

## Design Principles

### Simplicity
- No over-engineering
- Minimal dependencies
- Direct, straightforward code
- Avoid abstractions unless needed

### Mobile-First
- Touch targets ≥44px
- Responsive layouts
- Fast load times
- Offline capability

### No Build Complexity
- CDN for dependencies
- Edit and refresh workflow
- Pure HTML/CSS/JS
- No transpilation needed
