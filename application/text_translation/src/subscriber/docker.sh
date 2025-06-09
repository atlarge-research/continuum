#!/bin/bash
cp -r ../translator ./src/translator
docker buildx build --platform linux/amd64,linux/arm64 -t fzovpec2/text_translation:text_translation_subscriber_8 --push .
rm -rf src/translator