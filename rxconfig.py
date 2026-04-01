import reflex as rx

config = rx.Config(
    app_name="Anki_Card_Generator",
    state_auto_setters=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)
