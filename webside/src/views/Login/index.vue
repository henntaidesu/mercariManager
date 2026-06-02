<template>
  <div class="login-page">
    <el-card class="login-card" shadow="hover">
      <template #header>
        <div class="title-wrap">
          <div class="title-wrap__left">
            <el-icon size="26"><UserFilled /></el-icon>
            <span>{{ t('login.title') }}</span>
          </div>
          <el-select
            v-model="locale"
            size="small"
            class="login-lang-switcher"
            @change="onLocaleChange"
          >
            <el-option
              v-for="lang in localeOptions"
              :key="lang.value"
              :label="lang.label"
              :value="lang.value"
            />
          </el-select>
        </div>
      </template>

      <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('login.usernamePlaceholder')"
            size="large"
            clearable
            name="username"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('login.passwordPlaceholder')"
            size="large"
            show-password
            name="password"
            autocomplete="current-password"
          />
        </el-form-item>
        <el-form-item>
          <el-button native-type="submit" type="primary" size="large" :loading="loading" style="width: 100%">
            {{ t('login.login') }}
          </el-button>
        </el-form-item>
      </el-form>

      <div class="tip">{{ t('login.defaultAccount') }}</div>
    </el-card>
  </div>
</template>

<script src="./script.js"></script>
<style scoped src="./style.css"></style>
