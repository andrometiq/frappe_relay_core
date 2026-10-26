"""Channel contract: shared code asks a channel what it supports instead of comparing names."""

FEATURES = (
    'text', 'max_text_length', 'max_caption_length', 'media', 'location', 'contacts',
    'reply_quote', 'reactions', 'edits',
    'read_receipts', 'group_receipts',
    'templates', 'reply_window_hours', 'bulk_campaigns', 'forms', 'voice_calls',
    'groups', 'topics', 'email_threading', 'ai_automation', 'saved_replies',
)
ANY_FILE = '*/*'


class Channel:
    """One messaging channel and its fixed feature list."""
    name: str = ''
    features: dict = {}
    # Features that also need the Hub account flag of the same value, such as 'forms': 'flows'.
    account_flags: dict = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if set(cls.features) != set(FEATURES):
            raise TypeError(f'{cls.name} must declare exactly the contract features')

    def get_account_flags(self) -> dict:
        """Hub capability flags of the configured account."""
        raise NotImplementedError(f'{self.name} declares account flags but cannot read them')

    def get_features(self, flags: dict | None = None) -> dict:
        """Fixed features with account-gated ones switched off when the Hub flag is off."""
        if not self.account_flags:
            return dict(self.features)
        if flags is None:
            flags = self.get_account_flags()
        gated = {feature: bool(self.features[feature] and flags.get(flag)) for feature, flag in self.account_flags.items()}
        return {**self.features, **gated}

    def supports(self, feature: str, flags: dict | None = None) -> bool:
        if feature not in FEATURES:
            raise ValueError(f'Unknown channel feature: {feature}')
        return bool(self.get_features(flags)[feature])
